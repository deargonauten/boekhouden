"""Routes for /boeken* and /instellingen*. Parse input, call the ledger service, render.

No ledger logic lives here; see app.domain.ledger.
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain import ledger
from app.domain.ledger import LedgerError, NewEntry, NewLine
from app.domain.money import parse_euro
from app.seed.rgs_accounts import default_contexts

router = APIRouter(include_in_schema=False)

CONFLICT_CODES = {
    "PERIOD_LOCKED",
    "NO_OPEN_PERIOD",
    "ALREADY_REVERSED",
    "CANNOT_REVERSE_STORNO",
    "YEAR_EXISTS",
    "ACCOUNT_IN_USE",
    "SYSTEM_ACCOUNT",
}
ACCOUNT_TYPES = list(ledger.ACCOUNT_TYPE_LABELS.items())
JOURNAL_TYPES = list(ledger.JOURNAL_TYPE_LABELS.items())
# Glossary key that explains each account / journal type (label tables for the info icons).
ACCOUNT_TYPE_TERM = {
    "asset": "activa",
    "liability": "passiva",
    "equity": "eigen_vermogen",
    "revenue": "opbrengsten",
    "expense": "kosten",
}
JOURNAL_TYPE_TERM = {
    "verkoop": "verkoopdagboek",
    "inkoop": "inkoopdagboek",
    "bank": "bankdagboek",
    "kas": "kasdagboek",
    "memoriaal": "memoriaal",
}
MIN_ROWS = 2
PER_PAGE = 50
MAX_JOURNAL_TABS = 6


def _status_for(error: LedgerError) -> int:
    if error.code == "ACCOUNT_NOT_FOUND":
        return 404
    return 409 if error.code in CONFLICT_CODES else 422


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=status
    )


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# --- Boeken -----------------------------------------------------------------


@router.get("/boeken")
def entries_list(
    request: Request,
    dagboek: str | None = None,
    q: str | None = None,
    page: int = 1,
    session: Session = Depends(get_session),
):
    q = (q or "").strip()
    result = ledger.list_entries(
        session, journal_code=dagboek or None, q=q or None, page=max(page, 1), per_page=PER_PAGE
    )
    journals = [j for j in ledger.list_journals(session) if j.is_active or j.code == dagboek]
    return _render(
        request,
        "ledger/entries.html",
        title="Boeken",
        result=result,
        journals=journals,
        use_tabs=len(journals) <= MAX_JOURNAL_TABS,
        dagboek=dagboek or "",
        q=q,
    )


def _form_context(session: Session, **extra) -> dict:
    accounts = [a for a in ledger.list_accounts(session) if a.is_active and a.is_postable]
    vat_codes = [v for v in ledger.list_vat_codes(session) if v.is_active]
    return {
        "title": "Nieuwe boeking",
        "journals": [j for j in ledger.list_journals(session) if j.is_active],
        "account_groups": [
            (label, [a for a in accounts if a.type == key])
            for key, label in ACCOUNT_TYPES
            if any(a.type == key for a in accounts)
        ],
        "vat_codes": vat_codes,
        "active_vat_codes": {v.code for v in vat_codes},
        **extra,
    }


def _blank_row() -> dict:
    return {"account_id": "", "debit": "", "credit": "", "vat_code": "", "description": ""}


@router.get("/boeken/nieuw")
def entry_new(request: Request, session: Session = Depends(get_session)):
    # A manual booking belongs in the memoriaal; suggest it so the user only confirms.
    memoriaal_id = ledger.default_journal_id(session, "memoriaal")
    return _render(
        request,
        "ledger/entry_form.html",
        **_form_context(
            session,
            values={
                "journal_id": str(memoriaal_id) if memoriaal_id else "",
                "booking_date": date.today().isoformat(),
                "description": "",
                "reference": "",
            },
            rows=[_blank_row() for _ in range(MIN_ROWS)],
            errors=[],
            totals=None,
        ),
    )


@router.get("/boeken/nieuw/regel")
def entry_new_row(request: Request, session: Session = Depends(get_session)):
    return web.templates.TemplateResponse(
        request, "ledger/_line_row.html", {**_form_context(session), "row": _blank_row()}
    )


@router.post("/boeken/nieuw")
def entry_create(
    request: Request,
    journal_id: str = Form(""),
    booking_date: str = Form(""),
    description: str = Form(""),
    reference: str = Form(""),
    line_account: list[str] = Form(default=[]),
    line_debit: list[str] = Form(default=[]),
    line_credit: list[str] = Form(default=[]),
    line_vat: list[str] = Form(default=[]),
    line_description: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    values = {
        "journal_id": journal_id,
        "booking_date": booking_date,
        "description": description,
        "reference": reference,
    }
    rows = [
        {"account_id": a, "debit": d, "credit": c, "vat_code": v, "description": t}
        for a, d, c, v, t in zip(
            line_account, line_debit, line_credit, line_vat, line_description
        )
    ]
    errors: list[str] = []
    lines: list[NewLine] = []
    debit_total = credit_total = 0
    for n, row in enumerate(rows, start=1):
        if not any(v.strip() for v in row.values()):
            continue
        try:
            debit = parse_euro(row["debit"]) if row["debit"].strip() else 0
            credit = parse_euro(row["credit"]) if row["credit"].strip() else 0
        except (ValueError, LedgerError) as exc:
            errors.append(f"Regel {n}: {getattr(exc, 'message', None) or exc}")
            continue
        if not row["account_id"].isdigit():
            errors.append(f"Regel {n}: kies een rekening.")
            continue
        if bool(debit) == bool(credit):
            errors.append(f"Regel {n}: vul een bedrag in bij debet of credit, niet allebei.")
            continue
        debit_total += debit
        credit_total += credit
        lines.append(
            NewLine(
                account_id=int(row["account_id"]),
                debit_cents=debit,
                credit_cents=credit,
                description=row["description"].strip() or None,
                vat_code=row["vat_code"] or None,
            )
        )
    entry_date = None
    try:
        entry_date = date.fromisoformat(booking_date)
    except ValueError:
        errors.append("Vul een geldige datum in, bijvoorbeeld 31-12-2026.")
    if not journal_id.isdigit():
        errors.append("Kies in welk dagboek je wilt boeken.")

    status = 422
    if not errors:
        try:
            entry = ledger.post_entry(
                session,
                NewEntry(
                    journal_id=int(journal_id),
                    booking_date=entry_date,
                    description=description.strip(),
                    lines=lines,
                    reference=reference.strip() or None,
                ),
            )
            session.commit()
            return _see_other(f"/boeken/{entry.id}")
        except LedgerError as exc:
            session.rollback()
            errors.append(exc.message)
            status = _status_for(exc)
    return _render(
        request,
        "ledger/entry_form.html",
        status,
        **_form_context(
            session,
            values=values,
            rows=rows + [_blank_row() for _ in range(max(0, MIN_ROWS - len(rows)))],
            errors=errors,
            totals={
                "debit": debit_total,
                "credit": credit_total,
                "difference": debit_total - credit_total,
            },
        ),
    )


def _detail(request, detail, *, error=None, status=200):
    entry = detail.entry
    drawer = web.is_drawer_request(request, "boeking-drawer")
    return _render(
        request,
        "ledger/_entry_detail_body.html" if drawer else "ledger/entry_detail.html",
        status,
        title=entry.entry_number,
        entry=entry,
        detail=detail,
        error=error,
        reversible=detail.is_reversible,
        in_drawer=drawer,
        today=date.today().isoformat(),
    )


@router.get("/boeken/{entry_id:int}")
def entry_detail(
    request: Request, entry_id: int, session: Session = Depends(get_session)
):
    entry = ledger.get_entry(session, entry_id)
    if entry is None:
        return web.not_found_response(request)
    return _detail(request, entry)


@router.post("/boeken/{entry_id:int}/storno")
def entry_storno(
    request: Request,
    entry_id: int,
    datum: str = Form(""),
    session: Session = Depends(get_session),
):
    entry = ledger.get_entry(session, entry_id)
    if entry is None:
        return web.not_found_response(request)
    try:
        booking_date = date.fromisoformat(datum) if datum.strip() else None
    except ValueError:
        return _detail(request, entry, error="Vul een geldige datum in, bijvoorbeeld 31-12-2026.", status=422)
    try:
        storno = ledger.reverse_entry(session, entry_id, booking_date=booking_date)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _detail(request, entry, error=exc.message, status=_status_for(exc))
    return _see_other(f"/boeken/{storno.id}")


# --- Instellingen -----------------------------------------------------------


@router.get("/instellingen")
def settings_index() -> RedirectResponse:
    return RedirectResponse("/instellingen/grootboek", status_code=307)


def _context_values(type: str) -> dict:
    """Form suggestions for a new account: standaard btw-tarief and Selecteerbaar bij, by type."""
    purchase, sales, bank = default_contexts(type, False, "")
    return {
        "default_vat_code": "NL_21" if type == "expense" else "",
        "purchase": purchase,
        "sales": sales,
        "bank": bank,
    }


def _accounts_page(request, session, *, error=None, status=200, values=None, add_error=False):
    accounts = ledger.list_accounts(session)
    groups = [
        (label, ACCOUNT_TYPE_TERM[key], [a for a in accounts if a.type == key])
        for key, label in ACCOUNT_TYPES
    ]
    return _render(
        request,
        "ledger/accounts.html",
        status,
        title="Grootboek",
        groups=groups,
        account_types=ACCOUNT_TYPES,
        vat_codes=[v for v in ledger.list_vat_codes(session) if v.is_active],
        locked_ids={
            a.id
            for a in accounts
            if a.is_system and default_contexts(a.type, True, a.code) == (False, False, False)
        },
        error=error,
        add_error=add_error,
        values=values
        or {
            "code": ledger.suggest_account_code(session, "expense"),
            "name": "",
            "type": "expense",
            **_context_values("expense"),
        },
    )


@router.get("/instellingen/grootboek")
def accounts_page(request: Request, session: Session = Depends(get_session)):
    return _accounts_page(request, session)


@router.post("/instellingen/grootboek")
def accounts_add(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    type: str = Form(""),
    default_vat_code: str = Form(""),
    purchase: str = Form(""),
    sales: str = Form(""),
    bank: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        ledger.add_account(
            session,
            code=code.strip(),
            name=name.strip(),
            type=type,
            default_vat_code=default_vat_code or None,
            selectable_purchase=purchase == "1",
            selectable_sales=sales == "1",
            selectable_bank=bank == "1",
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _accounts_page(
            request,
            session,
            error=exc.message,
            add_error=True,
            status=_status_for(exc),
            values={
                "code": code,
                "name": name,
                "type": type,
                "default_vat_code": default_vat_code,
                "purchase": purchase == "1",
                "sales": sales == "1",
                "bank": bank == "1",
            },
        )
    return _see_other("/instellingen/grootboek")


@router.post("/instellingen/grootboek/{account_id:int}/actief")
def accounts_toggle(
    request: Request,
    account_id: int,
    active: str = Form("0"),
    session: Session = Depends(get_session),
):
    try:
        ledger.set_account_active(session, account_id, active == "1")
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _accounts_page(
            request, session, error=exc.message, status=_status_for(exc)
        )
    return _see_other("/instellingen/grootboek")


@router.post("/instellingen/grootboek/{account_id:int}/btw")
def accounts_vat_default(
    request: Request,
    account_id: int,
    vat_code: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        ledger.set_account_vat_default(session, account_id, vat_code or None)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _accounts_page(request, session, error=exc.message, status=_status_for(exc))
    return _see_other("/instellingen/grootboek")


@router.post("/instellingen/grootboek/{account_id:int}/selecteerbaar")
def accounts_contexts(
    request: Request,
    account_id: int,
    purchase: str = Form(""),
    sales: str = Form(""),
    bank: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        ledger.set_account_contexts(
            session,
            account_id,
            purchase=purchase == "1",
            sales=sales == "1",
            bank=bank == "1",
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _accounts_page(request, session, error=exc.message, status=_status_for(exc))
    return _see_other("/instellingen/grootboek")


def _default_cash_account(asset_accounts, journal_type: str) -> str:
    """Id of the one active asset account named Bank (or Kas), else empty."""
    word = {"bank": "bank", "kas": "kas"}.get(journal_type)
    matches = [a for a in asset_accounts if word and word in a.name.lower()]
    return str(matches[0].id) if len(matches) == 1 else ""


def _journals_page(request, session, *, error=None, status=200, values=None, add_error=False):
    accounts = ledger.list_accounts(session)
    asset_accounts = [a for a in accounts if a.type == "asset" and a.is_active]
    return _render(
        request,
        "ledger/journals.html",
        status,
        title="Dagboeken",
        journals=ledger.list_journals(session),
        journal_types=JOURNAL_TYPES,
        journal_type_labels=ledger.JOURNAL_TYPE_LABELS,
        journal_type_terms=JOURNAL_TYPE_TERM,
        asset_accounts=asset_accounts,
        error=error,
        add_error=add_error,
        values=values
        or {
            "code": "",
            "name": "",
            "type": "bank",
            "account_id": _default_cash_account(asset_accounts, "bank"),
        },
    )


@router.get("/instellingen/dagboeken")
def journals_page(request: Request, session: Session = Depends(get_session)):
    return _journals_page(request, session)


@router.post("/instellingen/dagboeken")
def journals_add(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    type: str = Form(""),
    account_id: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        ledger.add_journal(
            session,
            code=code.strip().upper(),
            name=name.strip(),
            type=type,
            account_id=int(account_id) if account_id.isdigit() else None,
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _journals_page(
            request,
            session,
            error=exc.message,
            add_error=True,
            status=_status_for(exc),
            values={"code": code, "name": name, "type": type, "account_id": account_id},
        )
    return _see_other("/instellingen/dagboeken")


@router.post("/instellingen/dagboeken/{journal_id:int}/actief")
def journals_toggle(
    request: Request,
    journal_id: int,
    active: str = Form("0"),
    session: Session = Depends(get_session),
):
    try:
        ledger.set_journal_active(session, journal_id, active == "1")
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _journals_page(
            request, session, error=exc.message, status=_status_for(exc)
        )
    return _see_other("/instellingen/dagboeken")


def _years_page(request, session, *, error=None, status=200):
    return _render(
        request,
        "ledger/fiscal_years.html",
        status,
        title="Boekjaren",
        years=ledger.list_fiscal_years(session),
        suggested_year=ledger.suggest_fiscal_year(session, date.today()),
        error=error,
    )


@router.get("/instellingen/boekjaren")
def years_page(request: Request, session: Session = Depends(get_session)):
    return _years_page(request, session)


@router.post("/instellingen/boekjaren")
def years_create(
    request: Request,
    year: int = Form(...),
    session: Session = Depends(get_session),
):
    try:
        ledger.create_fiscal_year(session, year)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _years_page(request, session, error=exc.message, status=_status_for(exc))
    return _see_other("/instellingen/boekjaren")


@router.post("/instellingen/boekjaren/periodes/{period_id:int}/vergrendel")
def period_lock(
    request: Request, period_id: int, session: Session = Depends(get_session)
):
    try:
        ledger.lock_period(session, period_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _years_page(request, session, error=exc.message, status=_status_for(exc))
    return _see_other("/instellingen/boekjaren")


@router.post("/instellingen/boekjaren/{year:int}/afsluiten")
def year_close(request: Request, year: int, session: Session = Depends(get_session)):
    try:
        ledger.close_fiscal_year(session, year)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _years_page(request, session, error=exc.message, status=_status_for(exc))
    return _see_other("/instellingen/boekjaren")
