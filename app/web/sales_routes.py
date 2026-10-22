"""Routes for /verkoop (verkoopfacturen, creditnota's, debiteuren, herinneringen).

Parse input, call the sales service, render. No sales logic lives here; see app.domain.sales.
"""

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain.documents.storage import DocumentStorage
from app.domain.errors import LedgerError
from app.domain.money import format_euro
from app.domain.relations import list_contacts
from app.domain.sales import (
    ConceptInput,
    LineInput,
    SalesError,
    build_document,
    compute_concept_totals,
    create_concept,
    create_credit_concept,
    create_reminder,
    debiteuren_overview,
    debtor_open_items,
    debtor_totals,
    delete_concept,
    draft_reminder,
    finalize,
    get_detail,
    get_invoice,
    list_documents,
    revenue_accounts,
    save_concept,
    stats,
    suggest_defaults,
    suggest_revenue_account,
)
from app.domain.sales import pdf as sales_pdf
from app.domain.sales.amounts import due_date as calc_due_date, format_quantity, parse_price, parse_quantity
from app.domain.sales.errors import INVALID_INPUT, NOT_FOUND
from app.domain.sales.service import STATUS_FILTERS, pdf_file_path
from app.domain.sales.types import BUCKET_LABELS, CONCEPT, CREDIT_NOTE, DEFINITIEF
from app.models import Contact, SalesReminder

router = APIRouter(include_in_schema=False)

PER_PAGE = 50
VAT_OPTIONS = (("NL_21", "21% (hoog tarief)"), ("NL_9", "9% (laag tarief)"), ("NL_0", "0%"))
STATUS_FILTER_LABELS = {
    "alle": "Alle", "concept": "Concept", "openstaand": "Openstaand", "te_laat": "Te laat", "betaald": "Betaald",
}
NOTICES = {
    "opgeslagen": "De factuur is opgeslagen als concept.",
    "definitief": "De factuur is definitief en vastgelegd in je administratie. Je kunt hem nu downloaden en versturen.",
    "verwijderd": "Het concept is weggegooid.",
    "creditnota": "De creditnota is klaar als concept. Controleer de aantallen en maak hem daarna definitief.",
    "herinnering": "De herinnering is gemaakt. Download de PDF of kopieer de tekst en stuur hem zelf naar de klant.",
}


def _cents_text(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


web.templates.env.filters["price_input"] = _cents_text
web.templates.env.filters["qty"] = format_quantity


def _storage(request: Request) -> DocumentStorage:
    return DocumentStorage(request.app.state.settings.documents_dir)


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=status
    )


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _status_for(error: LedgerError) -> int:
    if error.code == NOT_FOUND:
        return 404
    if error.code in ("PERIOD_LOCKED", "NO_OPEN_PERIOD"):
        return 409
    return 422


def _today() -> date:
    return date.today()


def _page_number(page: str) -> int:
    return int(page) if page.strip().isdigit() and int(page) > 0 else 1


# --- form parsing (text in, SalesError with a plain message out) ------------------------------------
def _parse_date(text: str, field_name: str, label: str, required: bool = True) -> date | None:
    text = (text or "").strip()
    if not text:
        if required:
            raise SalesError(INVALID_INPUT, f"Vul de {label} in.", field=field_name)
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise SalesError(INVALID_INPUT, f"Vul een geldige datum in bij {label}.", field=field_name) from None


@dataclass
class Values:
    """What the editor shows: the saved concept, or the user's own input after an error."""

    contact_id: str = ""
    invoice_date: str = ""
    payment_term_days: str = ""
    due_date: str = ""
    due_date_manual: bool = False
    service_date: str = ""
    reference: str = ""
    note: str = ""
    rows: list[dict] = field(default_factory=list)


def _blank_row(vat_code: str = "NL_21", account_id: str = "") -> dict:
    return {"description": "", "quantity": "1", "unit": "stuk", "price": "", "vat_code": vat_code,
            "account_id": account_id, "original_line_id": ""}


def _values_of(session: Session, invoice) -> Values:
    suggestions = {code: suggest_revenue_account(session, code) for code, _ in VAT_OPTIONS}
    rows = []
    for line in invoice.lines:
        follows = line.account_id is not None and line.account_id == suggestions.get(line.vat_code)
        rows.append({
            "description": line.description, "quantity": format_quantity(line.quantity_milli), "unit": line.unit,
            "price": _cents_text(line.unit_price_cents), "vat_code": line.vat_code,
            "account_id": "" if follows or line.account_id is None else str(line.account_id),
            "original_line_id": "" if line.original_line_id is None else str(line.original_line_id),
        })
    return Values(
        contact_id=str(invoice.contact_id), invoice_date=invoice.invoice_date.isoformat(),
        payment_term_days=str(invoice.payment_term_days) if invoice.kind != CREDIT_NOTE else "",
        due_date=invoice.due_date.isoformat(), due_date_manual=bool(invoice.due_date_manual),
        service_date=invoice.service_date.isoformat() if invoice.service_date else "",
        reference=invoice.reference or "", note=invoice.note or "", rows=rows,
    )


def _rows_from_form(descs, quantities, units, prices, vats, accounts, originals) -> list[dict]:
    rows = []
    for i, desc in enumerate(descs):
        get = lambda seq, default="": seq[i] if i < len(seq) else default  # noqa: E731
        rows.append({
            "description": desc, "quantity": get(quantities, "1"), "unit": get(units, "stuk"),
            "price": get(prices), "vat_code": get(vats, "NL_21"), "account_id": get(accounts),
            "original_line_id": get(originals),
        })
    return rows


def _values_from_form(**f) -> Values:
    return Values(
        contact_id=f["contact_id"], invoice_date=f["invoice_date"], payment_term_days=f["payment_term_days"],
        due_date=f["due_date"], due_date_manual=f["due_date_manual"] == "1", service_date=f["service_date"],
        reference=f["reference"], note=f["note"],
        rows=_rows_from_form(f["line_description"], f["line_quantity"], f["line_unit"], f["line_price"],
                             f["line_vat"], f["line_account"], f["line_original"]),
    )


def _parse_row(i: int, row: dict, credit: bool) -> LineInput | None:
    """One editor row as LineInput; None for a completely empty row. Messages name the row."""
    n = i + 1
    blank = not row["description"].strip() and not row["price"].strip()
    if blank and not credit:
        return None
    try:
        quantity = parse_quantity(row["quantity"])
    except SalesError as exc:
        raise SalesError(INVALID_INPUT, f"Regel {n}: {exc.message}", field=f"line-{i}-quantity") from None
    if credit:
        original = row["original_line_id"].strip()
        return LineInput("", quantity, 0, "NL_21", None, "stuk", int(original) if original.isdigit() else None)
    try:
        price = parse_price(row["price"]) if row["price"].strip() else 0
    except SalesError as exc:
        raise SalesError(INVALID_INPUT, f"Regel {n}: {exc.message}", field=f"line-{i}-price") from None
    account = row["account_id"].strip()
    return LineInput(
        row["description"], quantity, price, row["vat_code"], int(account) if account.isdigit() else None,
        row["unit"].strip() or "stuk",
    )


def _concept_input(values: Values, *, credit: bool, contact_id: int | None = None) -> ConceptInput:
    contact = contact_id if contact_id is not None else (int(values.contact_id) if values.contact_id.isdigit() else 0)
    term_text = values.payment_term_days.strip()
    if term_text and not term_text.isdigit():
        raise SalesError(INVALID_INPUT, "De betaaltermijn is een aantal dagen tussen 0 en 365, bijvoorbeeld 30.",
                         field="payment_term_days")
    invoice_date = _parse_date(values.invoice_date, "invoice_date", "factuurdatum")
    manual = values.due_date_manual and not credit
    lines = [l for i, row in enumerate(values.rows) if (l := _parse_row(i, row, credit)) is not None]
    return ConceptInput(
        contact_id=contact, invoice_date=invoice_date, lines=lines,
        payment_term_days=int(term_text) if term_text and not credit else None,
        due_date=_parse_date(values.due_date, "due_date", "vervaldatum", required=manual) if manual else None,
        due_date_manual=manual,
        service_date=_parse_date(values.service_date, "service_date", "leverdatum", required=False),
        reference=values.reference, note=values.note,
    )


# --- editor helpers ---------------------------------------------------------------------------------
def _effective_term(values: Values, defaults) -> int:
    """The betaaltermijn in days the vervaldatum follows: the typed one, else the suggestion."""
    text = values.payment_term_days.strip()
    return int(text) if text.isdigit() and int(text) <= 365 else defaults.payment_term_days


def _editor_context(session: Session, *, invoice=None, values: Values, errors=(), contact_id=None) -> dict:
    accounts = revenue_accounts(session)
    suggestions = {}
    for code, _label in VAT_OPTIONS:
        account_id = suggest_revenue_account(session, code)
        suggestions[code] = next((a for a in accounts if a.id == account_id), None)
    customers = list_contacts(session, role="customer")
    chosen = int(values.contact_id) if values.contact_id.isdigit() else None
    if chosen and all(c.id != chosen for c in customers):
        extra = session.get(Contact, chosen)
        if extra is not None:
            customers.append(extra)
    defaults = suggest_defaults(session, chosen, _today())
    credit = bool(invoice and invoice.kind == CREDIT_NOTE)
    return {
        "invoice": invoice, "values": values, "errors": list(errors), "accounts": accounts,
        "suggestions": suggestions, "vat_options": VAT_OPTIONS, "customers": customers, "defaults": defaults,
        "credit": credit, "original": get_invoice(session, invoice.credited_invoice_id) if credit else None,
        "totals": _live_totals(session, values, credit), "amounts": _line_amounts(session, values),
        "effective_term": _effective_term(values, defaults), "contact": session.get(Contact, chosen) if chosen else None,
    }


def _readable_lines(values: Values) -> list[tuple[int, LineInput]]:
    """(row index, line) of the rows that can be read; unreadable rows are skipped until they are fixed."""
    found = []
    for i, row in enumerate(values.rows):
        try:
            line = _parse_row(i, row, False)
        except SalesError:
            continue
        if line is not None and line.vat_code in dict(VAT_OPTIONS):
            found.append((i, line))
    return found


def _live_totals(session: Session, values: Values, credit: bool):
    """Totals of the rows that can be read; unreadable rows count as zero until they are fixed."""
    return compute_concept_totals(session, [line for _i, line in _readable_lines(values)])


def _line_amounts(session: Session, values: Values) -> list[str]:
    """Regeltotaal (zonder BTW) per editor row, formatted; empty for rows that cannot be read yet."""
    found = _readable_lines(values)
    totals = compute_concept_totals(session, [line for _i, line in found])
    amounts = [""] * len(values.rows)
    for (i, _line), cents in zip(found, totals.line_excl_cents):
        amounts[i] = format_euro(cents)
    return amounts


def _fix_link(error: SalesError, invoice) -> tuple[str, str] | None:
    """Where the user can fix what the error says."""
    field_name = getattr(error, "field", None)
    if field_name == "company":
        return "Vul je bedrijfsgegevens aan", "/instellingen/bedrijfsgegevens"
    if field_name == "contact" and invoice is not None:
        return "Vul de gegevens van de klant aan", f"/relaties/{invoice.contact_id}/bewerken"
    if field_name and invoice is not None:
        return "Pas de factuur aan", f"/verkoop/{invoice.id}"
    return None


# --- overview ---------------------------------------------------------------------------------------
def _tab_items(tab: str, q: str, status: str) -> list:
    return [
        ("Facturen", web.page_url("/verkoop", {"q": q, "status": status if status != "alle" else ""}, 1), tab == "facturen", None, "verkoopfactuur"),
        ("Debiteuren", "/verkoop/debiteuren", tab == "debiteuren", None, "debiteuren"),
    ]


@router.get("/verkoop", response_class=HTMLResponse)
def verkoop(
    request: Request,
    status: str = "alle",
    q: str = "",
    page: str = "1",
    melding: str = "",
    session: Session = Depends(get_session),
):
    status = status if status in STATUS_FILTERS else "alle"
    q = q.strip()
    today = _today()
    documents = list_documents(session, q=q or None, status=status, page=_page_number(page), per_page=PER_PAGE, today=today)
    has_any = list_documents(session, per_page=1, today=today).total > 0
    return _render(
        request, "sales/list.html", title="Verkoop", tab="facturen", status_filter=status, q=q, documents=documents,
        has_any=has_any, stats=stats(session, today), flash=NOTICES.get(melding),
        status_filters=STATUS_FILTER_LABELS, tab_items=_tab_items("facturen", q, status),
    )


@router.get("/verkoop/debiteuren", response_class=HTMLResponse)
def debiteuren(request: Request, session: Session = Depends(get_session)):
    today = _today()
    rows = debiteuren_overview(session, today)
    return _render(
        request, "sales/debtors.html", title="Verkoop", tab="debiteuren", rows=rows, totals=debtor_totals(rows),
        stats=stats(session, today), buckets=BUCKET_LABELS, tab_items=_tab_items("debiteuren", "", "alle"),
    )


@router.get("/verkoop/debiteuren/{contact_id:int}", response_class=HTMLResponse)
def debiteur_items(request: Request, contact_id: int, session: Session = Depends(get_session)):
    contact = session.get(Contact, contact_id)
    if contact is None:
        return web.not_found_response(request)
    items = debtor_open_items(session, contact_id, _today())
    return _render(
        request, "sales/debtor_items.html", title=f"Openstaand bij {contact.name}", contact=contact, items=items,
        total_cents=sum(i.open_cents for i in items), buckets=BUCKET_LABELS,
    )


# --- new / edit concept -----------------------------------------------------------------------------
def _new_values(session: Session, klant: int | None) -> Values:
    defaults = suggest_defaults(session, klant, _today())
    first = Values(
        contact_id=str(klant) if klant else "", invoice_date=defaults.invoice_date.isoformat(),
        due_date=defaults.due_date.isoformat(),
    )
    first.rows = [_blank_row("NL_21", "")]  # empty account choice = follow the suggestion
    return first


@router.get("/verkoop/nieuw", response_class=HTMLResponse)
def invoice_new(request: Request, klant: int | None = None, session: Session = Depends(get_session)):
    return _render(
        request, "sales/edit.html", title="Nieuwe factuur",
        **_editor_context(session, values=_new_values(session, klant)),
    )


@router.get("/verkoop/regel", response_class=HTMLResponse)
def line_row(request: Request, vat_code: str = "NL_21", session: Session = Depends(get_session)):
    """One extra empty line (htmx)."""
    ctx = _editor_context(session, values=Values())
    return _render(request, "sales/_line_row.html", row=_blank_row(vat_code if vat_code in dict(VAT_OPTIONS) else "NL_21"),
                   index=0, **ctx)


FORM_KEYS = ("contact_id", "invoice_date", "payment_term_days", "due_date", "due_date_manual", "service_date",
             "reference", "note")


@router.post("/verkoop/termijn", response_class=HTMLResponse)
def live_term(
    request: Request,
    contact_id: str = Form(""),
    invoice_date: str = Form(""),
    payment_term_days: str = Form(""),
    due_date: str = Form(""),
    due_date_manual: str = Form(""),
    session: Session = Depends(get_session),
):
    """Suggested betaaltermijn and vervaldatum for the chosen klant and factuurdatum (htmx); saves nothing."""
    try:
        day = date.fromisoformat(invoice_date.strip())
    except ValueError:
        day = _today()
    defaults = suggest_defaults(session, int(contact_id) if contact_id.strip().isdigit() else None, day)
    term_text = payment_term_days.strip()
    effective = int(term_text) if term_text.isdigit() and int(term_text) <= 365 else defaults.payment_term_days
    manual = due_date_manual == "1"
    values = Values(contact_id=contact_id, invoice_date=invoice_date, payment_term_days=payment_term_days,
                    due_date=due_date if manual else calc_due_date(day, effective).isoformat(), due_date_manual=manual)
    return _render(request, "sales/_term_fields.html", values=values, defaults=defaults, effective_term=effective,
                   oob=True)


@router.post("/verkoop/totalen", response_class=HTMLResponse)
def live_totals(
    request: Request,
    line_description: list[str] = Form([]),
    line_quantity: list[str] = Form([]),
    line_unit: list[str] = Form([]),
    line_price: list[str] = Form([]),
    line_vat: list[str] = Form([]),
    line_account: list[str] = Form([]),
    line_original: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    """Live totals while typing (htmx); never saves anything."""
    values = Values(rows=_rows_from_form(line_description, line_quantity, line_unit, line_price, line_vat,
                                         line_account, line_original))
    return _render(request, "sales/_totals.html", totals=_live_totals(session, values, False),
                   amounts=_line_amounts(session, values))


def _form_values(
    contact_id, invoice_date, payment_term_days, due_date, due_date_manual, service_date, reference, note,
    line_description, line_quantity, line_unit, line_price, line_vat, line_account, line_original,
) -> Values:
    return _values_from_form(
        contact_id=contact_id, invoice_date=invoice_date, payment_term_days=payment_term_days, due_date=due_date,
        due_date_manual=due_date_manual, service_date=service_date, reference=reference, note=note,
        line_description=line_description, line_quantity=line_quantity, line_unit=line_unit,
        line_price=line_price, line_vat=line_vat, line_account=line_account, line_original=line_original,
    )


@router.post("/verkoop/nieuw", response_class=HTMLResponse)
def invoice_create(
    request: Request,
    contact_id: str = Form(""),
    invoice_date: str = Form(""),
    payment_term_days: str = Form(""),
    due_date: str = Form(""),
    due_date_manual: str = Form(""),
    service_date: str = Form(""),
    reference: str = Form(""),
    note: str = Form(""),
    line_description: list[str] = Form([]),
    line_quantity: list[str] = Form([]),
    line_unit: list[str] = Form([]),
    line_price: list[str] = Form([]),
    line_vat: list[str] = Form([]),
    line_account: list[str] = Form([]),
    line_original: list[str] = Form([]),
    actie: str = Form("opslaan"),
    session: Session = Depends(get_session),
):
    values = _form_values(contact_id, invoice_date, payment_term_days, due_date, due_date_manual, service_date,
                          reference, note, line_description, line_quantity, line_unit, line_price, line_vat,
                          line_account, line_original)
    try:
        invoice = create_concept(session, _concept_input(values, credit=False))
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _render(request, "sales/edit.html", _status_for(exc), title="Nieuwe factuur",
                       **_editor_context(session, values=values, errors=[exc.message]))
    return _see_other(f"/verkoop/{invoice.id}/definitief" if actie == "definitief" else f"/verkoop/{invoice.id}?melding=opgeslagen")


@router.get("/verkoop/{invoice_id:int}", response_class=HTMLResponse)
def invoice_page(
    request: Request, invoice_id: int, melding: str = "", herinnering: int | None = None,
    session: Session = Depends(get_session),
):
    try:
        invoice = get_invoice(session, invoice_id)
    except SalesError:
        return web.not_found_response(request)
    if invoice.status == CONCEPT:
        title = "Creditnota bewerken" if invoice.kind == CREDIT_NOTE else "Factuur bewerken"
        return _render(request, "sales/edit.html", title=title, flash=NOTICES.get(melding),
                       **_editor_context(session, invoice=invoice, values=_values_of(session, invoice)))
    return _detail(request, session, invoice_id, melding=melding, reminder_id=herinnering)


def _detail(request: Request, session: Session, invoice_id: int, *, melding: str = "", reminder_id=None,
            errors=(), status: int = 200):
    detail = get_detail(session, invoice_id, _today())
    invoice = detail.invoice
    title = f"{'Creditnota' if invoice.kind == CREDIT_NOTE else 'Factuur'} {invoice.number}"
    return _render(
        request, "sales/detail.html", status, title=title, detail=detail, invoice=invoice, errors=list(errors),
        flash=NOTICES.get(melding), new_reminder=reminder_id,
        can_remind=detail.status == "te_laat" and invoice.kind != CREDIT_NOTE,
        mail=_invoice_mail(session, invoice) if invoice.kind != CREDIT_NOTE else None,
    )


def _mailto(email: str | None, subject: str, body: str) -> str | None:
    return f"mailto:{email}?subject={quote(subject)}&body={quote(body)}" if email else None


def _invoice_mail(session: Session, invoice) -> dict:
    """Proposed e-mail for sending a definitive invoice; the PDF must be attached by hand."""
    contact = session.get(Contact, invoice.contact_id)
    body = (
        f"Beste {invoice.buyer_name or contact.name},\n\n"
        f"Hierbij ontvang je factuur {invoice.number} van {invoice.invoice_date:%d-%m-%Y} "
        f"voor {_cents_text(invoice.total_incl_cents)} euro. "
        f"Wil je het bedrag uiterlijk {invoice.due_date:%d-%m-%Y} overmaken"
        f"{' naar ' + invoice.seller_iban if invoice.seller_iban else ''} onder vermelding van {invoice.number}?\n\n"
        f"Met vriendelijke groet,\n{invoice.seller_name or ''}"
    )
    return {"body": body, "url": _mailto(contact.email if contact else None, f"Factuur {invoice.number}", body)}


@router.post("/verkoop/{invoice_id:int}", response_class=HTMLResponse)
def invoice_save(
    request: Request,
    invoice_id: int,
    contact_id: str = Form(""),
    invoice_date: str = Form(""),
    payment_term_days: str = Form(""),
    due_date: str = Form(""),
    due_date_manual: str = Form(""),
    service_date: str = Form(""),
    reference: str = Form(""),
    note: str = Form(""),
    line_description: list[str] = Form([]),
    line_quantity: list[str] = Form([]),
    line_unit: list[str] = Form([]),
    line_price: list[str] = Form([]),
    line_vat: list[str] = Form([]),
    line_account: list[str] = Form([]),
    line_original: list[str] = Form([]),
    actie: str = Form("opslaan"),
    session: Session = Depends(get_session),
):
    try:
        invoice = get_invoice(session, invoice_id)
    except SalesError:
        return web.not_found_response(request)
    values = _form_values(contact_id, invoice_date, payment_term_days, due_date, due_date_manual, service_date,
                          reference, note, line_description, line_quantity, line_unit, line_price, line_vat,
                          line_account, line_original)
    credit = invoice.kind == CREDIT_NOTE
    try:
        data = _concept_input(values, credit=credit, contact_id=invoice.contact_id if credit else None)
        save_concept(session, invoice_id, data)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if invoice.status != CONCEPT:  # a definitief document is never edited
            return _detail(request, session, invoice_id, errors=[exc.message], status=_status_for(exc))
        return _render(request, "sales/edit.html", _status_for(exc),
                       title="Creditnota bewerken" if credit else "Factuur bewerken",
                       **_editor_context(session, invoice=invoice, values=values, errors=[exc.message]))
    return _see_other(f"/verkoop/{invoice_id}/definitief" if actie == "definitief" else f"/verkoop/{invoice_id}?melding=opgeslagen")


@router.post("/verkoop/{invoice_id:int}/verwijderen", response_class=HTMLResponse)
def invoice_delete(request: Request, invoice_id: int, session: Session = Depends(get_session)):
    try:
        delete_concept(session, invoice_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if exc.code == NOT_FOUND:
            return web.not_found_response(request)
        return _detail(request, session, invoice_id, errors=[exc.message], status=_status_for(exc))
    return _see_other("/verkoop?melding=verwijderd")


# --- definitief maken -------------------------------------------------------------------------------
def _confirm(request: Request, session: Session, invoice_id: int, errors=(), fix=None, status: int = 200):
    try:
        invoice = get_invoice(session, invoice_id)
    except SalesError:
        return web.not_found_response(request)
    if invoice.status != CONCEPT:
        return _see_other(f"/verkoop/{invoice_id}")
    contact = session.get(Contact, invoice.contact_id)
    return _render(request, "sales/confirm.html", status, title="Definitief maken", invoice=invoice,
                   contact=contact, errors=list(errors), fix=fix, credit=invoice.kind == CREDIT_NOTE,
                   original=get_invoice(session, invoice.credited_invoice_id) if invoice.credited_invoice_id else None)


@router.get("/verkoop/{invoice_id:int}/definitief", response_class=HTMLResponse)
def finalize_confirm(request: Request, invoice_id: int, session: Session = Depends(get_session)):
    return _confirm(request, session, invoice_id)


@router.post("/verkoop/{invoice_id:int}/definitief", response_class=HTMLResponse)
def finalize_invoice(request: Request, invoice_id: int, session: Session = Depends(get_session)):
    try:
        finalize(session, invoice_id, storage=_storage(request))
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if exc.code == NOT_FOUND:
            return web.not_found_response(request)
        invoice = get_invoice(session, invoice_id)
        return _confirm(request, session, invoice_id, errors=[exc.message],
                        fix=_fix_link(exc, invoice) if isinstance(exc, SalesError) else None, status=_status_for(exc))
    return _see_other(f"/verkoop/{invoice_id}?melding=definitief")


# --- PDF --------------------------------------------------------------------------------------------
def _pdf_response(content: bytes, filename: str) -> Response:
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/verkoop/{invoice_id:int}/pdf")
def invoice_pdf(request: Request, invoice_id: int, session: Session = Depends(get_session)):
    try:
        invoice = get_invoice(session, invoice_id)
    except SalesError:
        return web.not_found_response(request)
    label = "Creditnota" if invoice.kind == CREDIT_NOTE else "Factuur"
    if invoice.status == CONCEPT:  # preview, marked CONCEPT, never stored
        return _pdf_response(sales_pdf.render_invoice_pdf(build_document(session, invoice_id)),
                             f"Concept-{label.lower()}-{invoice_id}.pdf")
    path = pdf_file_path(_storage(request), invoice)
    if path is None or not path.is_file():
        return web.not_found_response(request)
    return _pdf_response(path.read_bytes(), f"{label}-{invoice.number}.pdf")


# --- creditnota -------------------------------------------------------------------------------------
@router.get("/verkoop/{invoice_id:int}/creditnota", response_class=HTMLResponse)
def credit_confirm(request: Request, invoice_id: int, session: Session = Depends(get_session)):
    try:
        detail = get_detail(session, invoice_id, _today())
    except SalesError:
        return web.not_found_response(request)
    error = None
    if not detail.can_credit:
        error = (
            "Bij een creditnota maak je geen creditnota." if detail.invoice.kind == CREDIT_NOTE
            else "Voor deze factuur kun je geen creditnota maken: hij is gestorneerd, nog een concept of al helemaal gecrediteerd."
        )
    return _render(request, "sales/credit_confirm.html", 422 if error else 200, title="Creditnota maken",
                   detail=detail, invoice=detail.invoice, errors=[error] if error else [])


@router.post("/verkoop/{invoice_id:int}/creditnota", response_class=HTMLResponse)
def credit_create(request: Request, invoice_id: int, session: Session = Depends(get_session)):
    try:
        note = create_credit_concept(session, invoice_id, _today())
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if exc.code == NOT_FOUND:
            return web.not_found_response(request)
        detail = get_detail(session, invoice_id, _today())
        return _render(request, "sales/credit_confirm.html", _status_for(exc), title="Creditnota maken",
                       detail=detail, invoice=detail.invoice, errors=[exc.message])
    return _see_other(f"/verkoop/{note.id}?melding=creditnota")


# --- herinnering ------------------------------------------------------------------------------------
def _reminder_page(request: Request, session: Session, invoice_id: int, reminder_date: str = "",
                   new_due_date: str = "", errors=(), status: int = 200):
    try:
        invoice = get_invoice(session, invoice_id)
    except SalesError:
        return web.not_found_response(request)
    errors = list(errors)
    draft = None
    try:
        draft = draft_reminder(
            session, invoice_id, _today(),
            reminder_date=_parse_date(reminder_date, "reminder_date", "datum van de herinnering", required=False),
            new_due_date=_parse_date(new_due_date, "new_due_date", "nieuwe vervaldatum", required=False),
        )
    except LedgerError as exc:
        errors.append(exc.message)
        status = 409 if status == 200 else status
        if status == 409 and exc.code == "INVALID_INPUT":
            status = 422
    mailto = _mailto(draft.contact_email, draft.mailto_subject, draft.body_text) if draft else None
    return _render(request, "sales/reminder.html", status, title="Betalingsherinnering maken", invoice=invoice,
                   draft=draft, errors=errors, mailto=mailto)


@router.get("/verkoop/{invoice_id:int}/herinnering", response_class=HTMLResponse)
def reminder_form(request: Request, invoice_id: int, reminder_date: str = "", new_due_date: str = "",
                  session: Session = Depends(get_session)):
    return _reminder_page(request, session, invoice_id, reminder_date, new_due_date)


@router.post("/verkoop/{invoice_id:int}/herinnering", response_class=HTMLResponse)
def reminder_create(request: Request, invoice_id: int, reminder_date: str = Form(""), new_due_date: str = Form(""),
                    session: Session = Depends(get_session)):
    try:
        reminder = create_reminder(
            session, invoice_id,
            reminder_date=_parse_date(reminder_date, "reminder_date", "datum van de herinnering", required=False),
            new_due_date=_parse_date(new_due_date, "new_due_date", "nieuwe vervaldatum", required=False),
            today=_today(), storage=_storage(request),
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if exc.code == NOT_FOUND:
            return web.not_found_response(request)
        status = 422 if exc.code in (INVALID_INPUT, "REMINDER_NOT_ALLOWED") else _status_for(exc)
        return _reminder_page(request, session, invoice_id, reminder_date, new_due_date, errors=[exc.message],
                              status=status)
    return _see_other(f"/verkoop/{invoice_id}?melding=herinnering&herinnering={reminder.id}")


@router.get("/verkoop/herinneringen/{reminder_id:int}/pdf")
def reminder_pdf(request: Request, reminder_id: int, session: Session = Depends(get_session)):
    reminder = session.get(SalesReminder, reminder_id)
    if reminder is None or not reminder.pdf_sha256:
        return web.not_found_response(request)
    path = _storage(request).path_for(reminder.pdf_sha256, "pdf")
    if not path.is_file():
        return web.not_found_response(request)
    invoice = get_invoice(session, reminder.invoice_id)
    return _pdf_response(path.read_bytes(), f"Herinnering-{reminder.level}-{invoice.number}.pdf")
