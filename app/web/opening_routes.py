"""Routes for /instellingen/beginbalans (Waarmee begin je?). Parse input, call the opening service, render.

No beginbalans logic lives here; see app.domain.opening. Money is parsed with app.domain.money.
"""

from dataclasses import dataclass, field
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain.errors import InvalidAmountError, LedgerError
from app.domain.money import parse_euro
from app.domain.opening import (
    CREDITEUR,
    DEBITEUR,
    OpeningError,
    OpeningInput,
    OpeningItemInput,
    allowed_accounts,
    book_opening_balance,
    first_fiscal_year,
    first_period_locked,
    get_opening_balance,
    preview,
)
from app.domain.relations import list_contacts

router = APIRouter(include_in_schema=False)

URL = "/instellingen/beginbalans"
SIDE_TITLES = {
    DEBITEUR: "Klanten die jou nog moeten betalen",
    CREDITEUR: "Leveranciers die jij nog moet betalen",
}
SIDE_NOUNS = {DEBITEUR: "klanten", CREDITEUR: "leveranciers"}


@dataclass
class ItemRow:
    """One openstaande factuur as typed (raw text), so a failed save keeps what the user entered."""

    contact_id: str = ""
    number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    amount: str = ""

    def is_empty(self) -> bool:
        return not any((self.contact_id, self.number.strip(), self.invoice_date, self.due_date, self.amount.strip()))


@dataclass
class FormState:
    balances: dict[int, str] = field(default_factory=dict)  # account_id -> typed amount
    rows: dict[str, list[ItemRow]] = field(default_factory=lambda: {DEBITEUR: [], CREDITEUR: []})


def plain_amount(cents: int) -> str:
    """Cents as '1250,00' for an input value (parse_euro reads it back)."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros},{rest:02d}"


def state_from_input(data: OpeningInput) -> FormState:
    state = FormState()
    for account_id, cents in data.balances:
        state.balances[account_id] = plain_amount(cents)
    for item in data.items:
        state.rows[item.side].append(ItemRow(
            contact_id=str(item.contact_id or ""),
            number=item.invoice_number,
            invoice_date=item.invoice_date.isoformat() if item.invoice_date else "",
            due_date=item.due_date.isoformat() if item.due_date else "",
            amount=plain_amount(item.amount_cents),
        ))
    return state


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


def parse_form(
    accounts,
    balance_account: list[str],
    balance_amount: list[str],
    item_side: list[str],
    item_contact: list[str],
    item_number: list[str],
    item_date: list[str],
    item_due: list[str],
    item_amount: list[str],
) -> tuple[OpeningInput, FormState, list[str]]:
    """Typed form -> domain input, the raw state to show again and plain-Dutch parse errors.

    Fully empty rows are dropped; a half-filled row goes on to the domain, which says what is missing.
    """
    labels = {str(a.id): f"{a.code} {a.name}" for a in accounts}
    errors: list[str] = []
    state = FormState()
    balances: list[tuple[int, int]] = []
    for raw_id, raw in zip(balance_account, balance_amount):
        if not raw_id.isdigit():
            continue
        state.balances[int(raw_id)] = raw
        if not raw.strip():
            continue
        try:
            balances.append((int(raw_id), parse_euro(raw)))
        except InvalidAmountError:
            errors.append(f"Vul bij {labels.get(raw_id, 'deze rekening')} een geldig bedrag in, bijvoorbeeld 1.250,00.")
    items: list[OpeningItemInput] = []
    counts = {DEBITEUR: 0, CREDITEUR: 0}
    n = max(map(len, (item_side, item_contact, item_number, item_date, item_due, item_amount)), default=0)

    def at(values: list[str], i: int) -> str:
        return values[i] if i < len(values) else ""

    for i in range(n):
        side = at(item_side, i)
        if side not in counts:
            continue
        row = ItemRow(at(item_contact, i), at(item_number, i), at(item_date, i), at(item_due, i), at(item_amount, i))
        state.rows[side].append(row)
        if row.is_empty():
            continue
        counts[side] += 1
        label = f"Openstaande factuur {counts[side]} ({SIDE_NOUNS[side]})"
        cents = 0
        if row.amount.strip():
            try:
                cents = parse_euro(row.amount)
            except InvalidAmountError:
                errors.append(f"{label}: vul een geldig bedrag in, bijvoorbeeld 1.250,00.")
        invoice_date, due_date = _parse_date(row.invoice_date), _parse_date(row.due_date)
        if row.invoice_date.strip() and invoice_date is None:
            errors.append(f"{label}: de factuurdatum is geen geldige datum.")
        if row.due_date.strip() and due_date is None:
            errors.append(f"{label}: de vervaldatum is geen geldige datum.")
        items.append(OpeningItemInput(
            side=side,
            contact_id=int(row.contact_id) if row.contact_id.isdigit() else None,
            invoice_number=row.number,
            invoice_date=invoice_date,
            due_date=due_date,
            amount_cents=cents,
        ))
    return OpeningInput(balances=balances, items=items), state, errors


# Glossary key that explains the bookkeeping-flavoured accounts (label table for the info icons).
ACCOUNT_TERM = {
    "0190": "cumulatieve_afschrijvingen",
    "1230": "kruisposten",
    "1400": "voorbelasting",
    "1410": "verlegd",
    "3100": "btw_af_te_dragen",
    "3110": "btw_af_te_dragen",
    "3120": "btw_af_te_dragen",
    "3130": "verlegd",
    "3140": "btw_af_te_dragen",
    "3150": "btw_rekening_courant",
}


def _contact_groups(session: Session, side: str):
    """Active relaties for the select: the matching role first, then the others."""
    flag = "is_customer" if side == DEBITEUR else "is_supplier"
    contacts = list_contacts(session)
    preferred = [c for c in contacts if getattr(c, flag)]
    others = [c for c in contacts if not getattr(c, flag)]
    groups = [
        ("Klanten" if side == DEBITEUR else "Leveranciers", preferred),
        ("Andere relaties" if preferred else "Relaties", others),
    ]
    return [(label, group) for label, group in groups if group]


def _page(request: Request, session: Session, *, state: FormState | None = None, data: OpeningInput | None = None,
          errors=(), status=200, notices=(), entry_id: int | None = None) -> HTMLResponse:
    fy = first_fiscal_year(session)
    ctx: dict = {"fy": fy, "errors": list(errors), "notices": list(notices), "booked_entry_id": entry_id}
    if fy is not None:
        view = get_opening_balance(session)
        if state is None:
            data = view.to_input() if view else OpeningInput()
            state = state_from_input(data)
        accounts = allowed_accounts(session)
        ctx.update(
            view=view,
            locked=first_period_locked(session),
            assets=[a for a in accounts if a.type == "asset"],
            liabilities=[a for a in accounts if a.type == "liability"],
            state=state,
            account_terms=ACCOUNT_TERM,
            summary=preview(session, data or OpeningInput()),
            sides=[(DEBITEUR, SIDE_TITLES[DEBITEUR]), (CREDITEUR, SIDE_TITLES[CREDITEUR])],
            contact_groups={s: _contact_groups(session, s) for s in (DEBITEUR, CREDITEUR)},
        )
    return web.templates.TemplateResponse(
        request, "opening/form.html", web.page_context(request, title="Beginbalans", **ctx), status_code=status
    )


@router.get(URL, response_class=HTMLResponse)
def opening_form(request: Request, melding: str = "", boeking: int | None = None,
                 session: Session = Depends(get_session)):
    booked = melding == "geboekt"
    return _page(request, session, notices=["De beginbalans is geboekt."] if booked else [],
                 entry_id=boeking if booked else None)


@router.get(f"{URL}/regel", response_class=HTMLResponse)
def opening_new_row(request: Request, side: str = DEBITEUR, session: Session = Depends(get_session)):
    side = side if side in SIDE_TITLES else DEBITEUR
    return web.templates.TemplateResponse(
        request, "opening/_item_row.html",
        {"side": side, "row": ItemRow(), "groups": _contact_groups(session, side)},
    )


def _form_fields(
    balance_account: list[str] = Form(default=[]),
    balance_amount: list[str] = Form(default=[]),
    item_side: list[str] = Form(default=[]),
    item_contact: list[str] = Form(default=[]),
    item_number: list[str] = Form(default=[]),
    item_date: list[str] = Form(default=[]),
    item_due: list[str] = Form(default=[]),
    item_amount: list[str] = Form(default=[]),
):
    return balance_account, balance_amount, item_side, item_contact, item_number, item_date, item_due, item_amount


@router.post(f"{URL}/controle", response_class=HTMLResponse)
def opening_check(request: Request, fields=Depends(_form_fields), session: Session = Depends(get_session)):
    """HTMX summary: the totals are computed here by the domain, never in the browser."""
    if first_fiscal_year(session) is None:
        return HTMLResponse("")
    data, _, _ = parse_form(allowed_accounts(session), *fields)
    return web.templates.TemplateResponse(request, "opening/_summary.html", {"summary": preview(session, data)})


@router.post(URL)
def opening_save(request: Request, fields=Depends(_form_fields), session: Session = Depends(get_session)):
    data, state, errors = parse_form(allowed_accounts(session), *fields)
    if errors:
        return _page(request, session, state=state, data=data, errors=errors, status=422)
    try:
        entry = book_opening_balance(session, data)
        session.commit()
    except OpeningError as exc:
        session.rollback()
        if exc.code == "UNCHANGED":
            return _page(request, session, state=state, data=data, notices=[exc.message])
        return _page(request, session, state=state, data=data, errors=[exc.message], status=422)
    except LedgerError as exc:
        session.rollback()
        return _page(request, session, state=state, data=data, errors=[exc.message], status=422)
    return RedirectResponse(f"{URL}?melding=geboekt&boeking={entry.id}", status_code=303)
