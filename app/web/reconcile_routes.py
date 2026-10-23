"""Routes for bank reconciliation (/bank/afletteren, /bank/regels): bank transactions linked to invoices.

Thin handlers: parse input, call app.domain.reconcile, render. No reconciliation logic lives here;
the domain only flushes, so these handlers commit (or roll back on a refused booking).
"""

from dataclasses import dataclass, field
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain import ledger
from app.domain import reconcile as rec
from app.domain.bank import accounts as bank_accounts
from app.domain.errors import InvalidAmountError, LedgerError
from app.domain.money import parse_euro
from app.domain.reconcile import errors as rec_errors
from app.domain.relations import list_contacts

router = APIRouter(include_in_schema=False)

PER_PAGE = 50
LIST_URL = "/bank/afletteren"
NOT_FOUND_CODES = {rec_errors.NOT_FOUND, rec_errors.RULE_NOT_FOUND}
CONFLICT_CODES = {
    rec_errors.ALREADY_PROCESSED,
    rec_errors.NOT_BOOKED,
    rec_errors.NOT_IGNORED,
    rec_errors.IGNORED,
}
STATUS_TABS = ("nieuw", "genegeerd")
EXTRA_LINES = 2  # empty rows offered under the direct-booking lines
HIDDEN_ACCOUNT_CODES = {"3000", "1400", "1300"}  # crediteuren, voorbelasting and debiteuren are booked by the system

MELDINGEN = {
    "geboekt": "De mutatie is geboekt.",
    "genegeerd": "De mutatie is genegeerd en komt niet in je boekhouding.",
    "teruggezet": "De mutatie staat weer bij de mutaties die je nog moet verwerken.",
    "ongedaan": "De boeking is ongedaan gemaakt. De mutatie staat weer klaar om te verwerken.",
    "regel_aan": "De onthouden keuze staat weer aan.",
    "regel_uit": "De onthouden keuze staat uit en wordt niet meer voorgesteld.",
}


def status_for(error: LedgerError) -> int:
    """HTTP status by error code (never by base class): 404 for missing things, 409 when the
    transaction is in the wrong state, 422 for everything the user can fix in the form."""
    if error.code in NOT_FOUND_CODES:
        return 404
    if error.code in CONFLICT_CODES:
        return 409
    return 422


def _render(request: Request, template: str, http_status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=http_status
    )


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _safe_back(value: str | None) -> str:
    """Where to return to after an action: only our own list page (no open redirect)."""
    value = (value or "").strip()
    if value.startswith(LIST_URL) and "//" not in value and "\\" not in value and "\n" not in value:
        return value
    return LIST_URL


def _list_url(params: dict) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return LIST_URL + (f"?{query}" if query else "")


def _with_melding(url: str, key: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}{urlencode({'melding': key})}"


# --- list -----------------------------------------------------------------------------------------------------


def _list_context(
    session: Session, rekening: int | None, q: str, richting: str, status: str, page: int
) -> dict:
    richting = richting if richting in ("af", "bij") else ""
    status = status if status in STATUS_TABS else "nieuw"
    result = rec.list_to_process(
        session, bank_account_id=rekening, q=q or None, direction=richting or None,
        status=status, page=max(1, page), per_page=PER_PAGE,
    )
    accounts = bank_accounts.list_bank_accounts(session)
    params = {"rekening": rekening, "q": q, "richting": richting, "status": status if status != "nieuw" else ""}
    return {
        "result": result,
        "accounts": accounts,
        "rekening": rekening,
        "q": q,
        "richting": richting,
        "status": status,
        "params": params,
        "back": _list_url({**params, "page": result.page if result.page > 1 else ""}),
        "to_process": rec.to_process_count(session),
    }


def _list_page(request: Request, session: Session, *, error=None, melding="", status_code=200, **filters):
    ctx = _list_context(
        session, filters.get("rekening"), filters.get("q", ""), filters.get("richting", ""),
        filters.get("status", "nieuw"), filters.get("page", 1),
    )
    if request.headers.get("HX-Target") == "reconcile-rows" and error is None:
        return _render(request, "bank/_reconcile_rows.html", **ctx)
    return _render(
        request, "bank/reconcile_list.html", status_code, title="Afletteren", error=error,
        melding_text=MELDINGEN.get(melding, ""), **ctx,
    )


@router.get(LIST_URL, response_class=HTMLResponse)
def reconcile_list(
    request: Request,
    rekening: str = "",
    q: str = "",
    richting: str = "",
    status: str = "nieuw",
    page: int = 1,
    melding: str = "",
    session: Session = Depends(get_session),
):
    return _list_page(
        request, session, melding=melding, rekening=_to_int(rekening), q=q.strip(),
        richting=richting, status=status, page=page,
    )


@router.post("/bank/transacties/{txn_id:int}/akkoord", response_class=HTMLResponse)
async def reconcile_accept(request: Request, txn_id: int, session: Session = Depends(get_session)):
    form = await request.form()
    back = _safe_back(str(form.get("terug", "")))
    try:
        rec.accept(session, txn_id, str(form.get("suggestion", "")))
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if status_for(exc) == 404:
            return web.not_found_response(request)
        return _list_page(request, session, error=exc.message, status_code=status_for(exc))
    return _see_other(_with_melding(back, "geboekt"))


# --- detail / manual match ------------------------------------------------------------------------------------


@dataclass
class DetailState:
    """What the user typed on the match page, so a refused booking keeps it."""

    contact: str = ""
    q: str = ""
    checked: set[str] = field(default_factory=set)  # "source:id"
    amounts: dict[str, str] = field(default_factory=dict)
    lines: list[dict] = field(default_factory=list)  # account, vat, amount, description
    remember: bool = False
    needle: str = ""
    soort: str = ""  # snelkeuze: '' | 'btw' | 'prive'
    aangifte: str = ""
    posted: bool = False
    back: str = LIST_URL


def _item_key(item: rec.OpenItem) -> str:
    return f"{item.source}:{item.source_id}"


def _plain_amount(cents: int) -> str:
    euros, rest = divmod(abs(cents), 100)
    return f"{euros},{rest:02d}"


def _empty_line() -> dict:
    return {"account": "", "vat": "", "amount": "", "description": ""}


def _parse_amount(text: str) -> int | None:
    try:
        return parse_euro(text)
    except InvalidAmountError:
        return None


async def _read_state(request: Request) -> DetailState:
    form = await request.form()
    state = DetailState(
        contact=str(form.get("contact", "")).strip(),
        q=str(form.get("q", "")).strip(),
        remember=bool(form.get("remember")),
        needle=str(form.get("remember_needle", "")).strip(),
        soort=str(form.get("soort", "")).strip(),
        aangifte=str(form.get("aangifte", "")).strip(),
        posted=True,
        back=_safe_back(str(form.get("terug", ""))),
    )
    for key in form.getlist("item"):
        state.checked.add(str(key))
    for key, value in form.multi_items():
        if key.startswith("amount_"):
            source, _, source_id = key.removeprefix("amount_").rpartition("_")
            state.amounts[f"{source}:{source_id}"] = str(value)
    accounts = form.getlist("line_account")
    vats = form.getlist("line_vat")
    amounts = form.getlist("line_amount")
    descriptions = form.getlist("line_description")
    for i in range(max(len(accounts), len(vats), len(amounts), len(descriptions), 0)):
        state.lines.append({
            "account": str(accounts[i]) if i < len(accounts) else "",
            "vat": str(vats[i]) if i < len(vats) else "",
            "amount": str(amounts[i]) if i < len(amounts) else "",
            "description": str(descriptions[i]) if i < len(descriptions) else "",
        })
    return state


def _parse_state(session: Session, state: DetailState, txn_id: int):
    """Typed state -> domain input plus plain-Dutch parse errors. Fully empty direct lines are dropped."""
    errors: list[str] = []
    known = {_item_key(i): i for i in rec.list_all_open_items(session)}
    allocations: list[rec.Allocation] = []
    for key in sorted(state.checked):
        item = known.get(key)
        if item is None:
            errors.append("Een gekozen factuur staat niet meer open. Ververs de pagina en kies opnieuw.")
            continue
        cents = _parse_amount(state.amounts.get(key, ""))
        if cents is None or cents <= 0:
            errors.append(
                f"Vul bij factuur {item.number} een geldig bedrag in, bijvoorbeeld 121,00."
            )
            continue
        allocations.append(rec.Allocation(item.source, item.source_id, cents))
    directs: list[rec.DirectLine] = []
    if state.soort:
        try:
            directs.append(rec.quick_line(session, txn_id, state.soort, state.aangifte))
        except LedgerError as exc:
            errors.append(exc.message)
        return allocations, directs, errors, known
    for line in state.lines:
        if not any(v.strip() for v in line.values()):
            continue
        if not line["account"].strip() and not line["amount"].strip():
            continue  # only a btw-code or text: nothing to book
        cents = _parse_amount(line["amount"]) if line["amount"].strip() else None
        if cents is None or cents <= 0:
            errors.append("Vul bij elke boeking zonder factuur een geldig bedrag in, bijvoorbeeld 2,50.")
            continue
        directs.append(rec.DirectLine(
            _to_int(line["account"]), cents, line["vat"].strip() or None, line["description"].strip() or None
        ))
    return allocations, directs, errors, known


def _summary(detail: rec.TransactionDetail, allocations, directs, known) -> dict:
    """Server-side totals for 'Verdeeld X van Y, nog Z te verdelen'."""
    direction = detail.txn.direction
    total = detail.txn.abs_cents
    distributed = sum(line.amount_cents for line in directs)
    for a in allocations:
        item = known.get(f"{a.source}:{a.source_id}")
        follows = item is not None and rec.money_follows(direction, item.side, item.is_credit)
        distributed += a.amount_cents if follows else -a.amount_cents
    return {"total": total, "distributed": distributed, "remainder": total - distributed}


def _account_groups(session: Session, bank_ledger_id: int):
    accounts = [
        a for a in ledger.list_accounts(session)
        if a.is_active and a.is_postable and a.id != bank_ledger_id
        and a.code not in HIDDEN_ACCOUNT_CODES and not (a.is_system and a.type == "asset")
    ]
    return [
        (label, [a for a in accounts if a.type == key])
        for key, label in ledger.ACCOUNT_TYPE_LABELS.items()
        if any(a.type == key for a in accounts)
    ]


def _open_items_for(session: Session, state: DetailState, detail: rec.TransactionDetail):
    contact_id = _to_int(state.contact)
    if contact_id is None and not state.q:
        contact_id = detail.default_contact_id
    if contact_id is not None:
        return contact_id, rec.list_all_open_items(session, contact_id=contact_id, q=state.q or None)
    if state.q:
        return None, rec.list_all_open_items(session, q=state.q)
    return None, []


def _initial_state(session: Session, detail: rec.TransactionDetail, items: list, suggestion) -> DetailState:
    """Prefill: the suggested invoices ticked, amounts capped by what is left, defaults for direct booking."""
    state = DetailState()
    remaining = detail.txn.abs_cents
    suggested = {(a.source, a.source_id): a.amount_cents for a in suggestion.allocations} if suggestion else {}
    for item in items:
        key = _item_key(item)
        take = suggested.get(item.ref)
        if take is not None:
            state.checked.add(key)
            remaining -= take if rec.money_follows(detail.txn.direction, item.side, item.is_credit) else -take
        state.amounts[key] = _plain_amount(take if take is not None else min(item.open_cents, max(remaining, 0)))
    default = rec.direct_defaults(session, detail.txn.id)
    first = _empty_line()
    if default is not None and default.account_id:
        first["account"] = str(default.account_id)
        first["vat"] = default.vat_code or rec.default_vat_for(session, default.account_id) or ""
        first["description"] = default.description or ""
        if not state.checked:
            first["amount"] = _plain_amount(default.amount_cents)
    state.lines = [first]
    return state


def _detail_page(
    request: Request,
    session: Session,
    txn_id: int,
    state: DetailState | None = None,
    *,
    error=None,
    melding="",
    status_code=200,
    back=LIST_URL,
):
    try:
        detail = rec.get_transaction_detail(session, txn_id)
    except LedgerError as exc:
        return _not_found_or_error(request, exc)
    ctx: dict = {"detail": detail, "error": error, "melding_text": MELDINGEN.get(melding, ""), "state": state, "back": back}
    if detail.status == "nieuw":
        suggestions = rec.suggestions_for(session, txn_id)
        best = suggestions[0] if suggestions else None
        base = state or DetailState()
        customers = list_contacts(session, role="customer")
        contact_id, items = _open_items_for(session, base, detail)
        if state is None or not state.posted:
            state = _initial_state(session, detail, items, best if best and best.kind == "match" else None)
            state.contact = str(contact_id or "")
            state.q = base.q
        else:
            state.contact = state.contact or str(contact_id or "")
        allocations, directs, _, known = _parse_state(session, state, txn_id)
        lines = list(state.lines)
        while lines and not any(v.strip() for v in lines[-1].values()):
            lines.pop()
        lines += [_empty_line() for _ in range(EXTRA_LINES)]
        ctx.update(
            state=state,
            items=items,
            contact_id=contact_id,
            customers=customers,
            suppliers=[c for c in list_contacts(session, role="supplier") if c.id not in {x.id for x in customers}],
            account_groups=_account_groups(session, detail.bank_account_ledger_id),
            vat_codes=[v for v in ledger.list_vat_codes(session) if v.is_active],
            lines=lines,
            summary=_summary(detail, allocations, directs, known),
            vat_periods=rec.vat_period_choices(session, txn_id),
            can_remember=True,
            has_iban=bool(detail.txn.counterparty_iban),
        )
    return _render(
        request, "bank/reconcile_detail.html", status_code, title="Mutatie verwerken", **ctx
    )


def _not_found_or_error(request: Request, exc: LedgerError):
    return web.not_found_response(request)


@router.get("/bank/transacties/{txn_id:int}/afletteren", response_class=HTMLResponse)
def reconcile_detail(
    request: Request,
    txn_id: int,
    contact: str = "",
    q: str = "",
    melding: str = "",
    terug: str = "",
    session: Session = Depends(get_session),
):
    state = DetailState(contact=contact.strip(), q=q.strip()) if (contact or q) else None
    return _detail_page(request, session, txn_id, state, melding=melding, back=_safe_back(terug))


@router.post("/bank/transacties/{txn_id:int}/afletteren", response_class=HTMLResponse)
async def reconcile_book(request: Request, txn_id: int, session: Session = Depends(get_session)):
    state = await _read_state(request)
    back = state.back
    allocations, directs, errors, _ = _parse_state(session, state, txn_id)
    if errors:
        return _detail_page(request, session, txn_id, state, error=errors, status_code=422, back=back)
    draft = None
    if state.remember:
        draft = rec.RuleDraft(
            use_iban=True, description_contains=state.needle or None,
            contact_id=_to_int(state.contact),
        )
    try:
        rec.book(session, txn_id, allocations, directs, remember_rule=draft)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if status_for(exc) == 404:
            return web.not_found_response(request)
        return _detail_page(request, session, txn_id, state, error=exc.message, status_code=status_for(exc), back=back)
    return _see_other(_with_melding(back, "geboekt"))


@router.post("/bank/transacties/{txn_id:int}/afletteren/controle", response_class=HTMLResponse)
async def reconcile_summary(request: Request, txn_id: int, session: Session = Depends(get_session)):
    """HTMX summary: totals are computed here, never in the browser. Bad input is ignored."""
    try:
        detail = rec.get_transaction_detail(session, txn_id)
    except LedgerError:
        return HTMLResponse("")
    state = await _read_state(request)
    allocations, directs, _, known = _parse_state(session, state, txn_id)
    return web.templates.TemplateResponse(
        request, "bank/_reconcile_summary.html", {"summary": _summary(detail, allocations, directs, known)}
    )


# --- negeren / terugzetten / ongedaan maken -----------------------------------------------------------------


def _simple_action(request: Request, session: Session, txn_id: int, action, melding: str, target: str):
    try:
        action(session, txn_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if status_for(exc) == 404:
            return web.not_found_response(request)
        return _detail_page(request, session, txn_id, error=exc.message, status_code=status_for(exc))
    return _see_other(_with_melding(target, melding))


@router.post("/bank/transacties/{txn_id:int}/negeren", response_class=HTMLResponse)
async def reconcile_ignore(request: Request, txn_id: int, session: Session = Depends(get_session)):
    form = await request.form()
    return _simple_action(
        request, session, txn_id, rec.ignore, "genegeerd", _safe_back(str(form.get("terug", "")))
    )


@router.post("/bank/transacties/{txn_id:int}/terugzetten", response_class=HTMLResponse)
def reconcile_restore(request: Request, txn_id: int, session: Session = Depends(get_session)):
    return _simple_action(
        request, session, txn_id, rec.restore, "teruggezet", f"/bank/transacties/{txn_id}/afletteren"
    )


@router.post("/bank/transacties/{txn_id:int}/ongedaan-maken", response_class=HTMLResponse)
def reconcile_undo(request: Request, txn_id: int, session: Session = Depends(get_session)):
    return _simple_action(
        request, session, txn_id, rec.undo, "ongedaan", f"/bank/transacties/{txn_id}/afletteren"
    )


# --- onthouden keuzes ------------------------------------------------------------------------------------------


def _rules_page(request: Request, session: Session, *, error=None, melding="", status_code=200):
    return _render(
        request, "bank/rules.html", status_code, title="Onthouden keuzes", rules=rec.list_rules(session),
        vat_names={v.code: v.name for v in ledger.list_vat_codes(session)},
        error=error, melding_text=MELDINGEN.get(melding, ""),
    )


@router.get("/bank/regels", response_class=HTMLResponse)
def rules_list(request: Request, melding: str = "", session: Session = Depends(get_session)):
    return _rules_page(request, session, melding=melding)


@router.post("/bank/regels/{rule_id:int}/actief", response_class=HTMLResponse)
async def rules_toggle(request: Request, rule_id: int, session: Session = Depends(get_session)):
    form = await request.form()
    active = str(form.get("actief", "")) == "1"
    try:
        rec.set_rule_active(session, rule_id, active)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if status_for(exc) == 404:
            return web.not_found_response(request)
        return _rules_page(request, session, error=exc.message, status_code=status_for(exc))
    return _see_other(_with_melding("/bank/regels", "regel_aan" if active else "regel_uit"))

