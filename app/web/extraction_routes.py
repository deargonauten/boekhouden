"""Routes for reading out (uitlezen) and reviewing (nakijken) inbox documents.

Thin handlers: parse the request, call app.domain.extraction, render. The only
orchestration done here is the three-step flow of spec 5.3 (build request, call the
extractor outside any write transaction, store the result) because the commits
between the steps belong to the request, not to the domain.
"""

import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain import ledger, reconcile
from app.domain.documents import (
    STATUS_LABELS,
    DocumentError,
    DocumentStorage,
    count_by_status,
    get_document,
    list_documents,
)
from app.domain.errors import (
    LedgerError,
    DocumentNotFoundError,
    ExtractionError,
    ExtractionNotAllowedError,
    ExtractionNotFoundError,
    ExtractionRateLimitedError,
    ExtractorUnavailableError,
    ReviewValidationError,
)
from app.domain.extraction import (
    ReviewInput,
    ReviewLineInput,
    backend_status,
    build_request,
    get_extraction,
    next_document_to_review,
    save_review,
    store_failure,
    store_result,
)
from app.domain.extraction.extractors.factory import get_extractor
from app.domain.fx import format_rate
from app.domain.money import format_euro
from app.domain.purchase import book_extraction
from app.domain.purchase.booking import DEFAULT_SHIFTED_VAT_BP
from app.models import Account, Contact
from app.web.inbox_routes import DOCUMENT_STATUSES, LIST_LIMIT, _list_page, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

BATCH_LIMIT = 10
LEVELS = ("low", "medium")  # flag levels that count as "controleer dit"
LEVEL_LABELS = {"medium": "Controleer", "low": "Onzeker"}
SAVED_MESSAGE = "Opgeslagen."
DELETED_MESSAGE = "Dit document is ondertussen verwijderd. Ga terug naar je inbox."
BOOKED_NEXT_MESSAGE = "De vorige factuur is geboekt. Dit is de volgende."
FINISHED_MESSAGE = "Klaar met nakijken. De volgende stap is boeken."
NO_ACCOUNT_HINT = "Kies een rekening. Twijfel je? Kies 4999 Nog te verdelen."
HEADER_FIELDS = (
    "supplier_name", "supplier_kvk", "supplier_btw_number", "supplier_iban",
    "supplier_address_line", "supplier_postal_code", "supplier_city", "supplier_country",
    "invoice_number", "invoice_date", "due_date", "currency",
    "total_excl", "total_vat", "total_incl", "exchange_rate", "shifted_vat_rate",
)
LINE_FIELDS = ("description", "amount_excl", "vat_code", "vat_amount", "account_code", "source_text")
FIELD_LABELS = {
    "supplier_name": "Leverancier", "supplier_kvk": "KvK-nummer",
    "supplier_btw_number": "Btw-nummer", "supplier_iban": "IBAN",
    "invoice_number": "Factuurnummer", "invoice_date": "Factuurdatum",
    "due_date": "Vervaldatum", "currency": "Valuta", "totals": "Totalen",
    "exchange_rate": "Wisselkoers", "shifted_vat_rate": "Btw-tarief voor verlegde btw",
    "total_excl": "Bedrag zonder BTW", "total_vat": "BTW", "total_incl": "Totaal incl. BTW",
    "kind": "Soort document",
}


# --- template helpers --------------------------------------------------------


def _amount_text(cents: int | None) -> str:
    """Cents as editable Dutch text without the euro sign: 1.234,56."""
    return "" if cents is None else format_euro(cents).replace("€ ", "")


def _date_text(value) -> str:
    return "" if value is None else value.strftime("%d-%m-%Y")


def _backend_kind(settings) -> str:
    """'cli', 'api' or 'none' from backend_status(); never raises (a banner must not break a page)."""
    try:
        raw = backend_status(settings)
    except Exception:  # noqa: BLE001
        logger.exception("backend_status failed")
        return "none"
    return {"claude_cli": "cli", "anthropic_api": "api"}.get(raw.kind, "none")


web.templates.env.globals["extract_backend"] = lambda request: _backend_kind(
    request.app.state.settings
)
web.templates.env.filters["datum_veld"] = _date_text


# --- injected extractor --------------------------------------------------------


class _UnavailableExtractor:
    """Stands in when no backend is usable, so the route can store a plain-Dutch failure."""

    name = "unavailable"
    model = None

    def __init__(self, error: ExtractorUnavailableError):
        self.error = error

    def extract(self, request):
        raise self.error


def get_extractor_dep(request: Request):
    try:
        return get_extractor(request.app.state.settings)
    except ExtractorUnavailableError as exc:
        return _UnavailableExtractor(exc)


# --- shared flow -----------------------------------------------------------------


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=status
    )


def _load(session: Session, document_id: int):
    try:
        return get_document(session, document_id)
    except DocumentError as exc:
        if exc.code == "DOCUMENT_NOT_FOUND":
            return None
        raise


def _extract_one(
    session: Session, storage: DocumentStorage, extractor, document_id: int
) -> ExtractionError | None:
    """Read one document. Returns the typed error (already stored as a failed
    extraction) or None on success. ExtractionNotAllowedError is raised, not returned.
    The extractor runs between two commits so SQLite is not locked while it works."""
    request = build_request(session, storage, document_id)
    session.commit()
    try:
        invoice = extractor.extract(request)
    except ExtractionError as exc:
        session.expire_all()  # re-read: the document may have been deleted meanwhile
        store_failure(session, document_id, extractor.name, exc)
        session.commit()
        return exc
    session.expire_all()
    store_result(session, document_id, extractor.name, extractor.model, invoice)
    session.commit()
    return None


def _detail_page(request: Request, document, status: int = 200, **ctx):
    return _render(
        request,
        "inbox/detail.html",
        status,
        title=document.original_filename,
        document=document,
        status_label=STATUS_LABELS[document.status],
        **ctx,
    )


def _deleted_meanwhile(request: Request, session: Session):
    """The document was deleted while we worked on it: say so in plain Dutch, no 500."""
    session.rollback()
    results = [{"kind": "error", "name": "", "message": DELETED_MESSAGE}]
    return _list_page(request, session, results=results, status=404)


@router.post("/inbox/{document_id:int}/uitlezen")
def extract_document(
    request: Request,
    document_id: int,
    session: Session = Depends(get_session),
    storage: DocumentStorage = Depends(get_storage),
    extractor=Depends(get_extractor_dep),
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    try:
        error = _extract_one(session, storage, extractor, document_id)
    except ExtractionNotAllowedError as exc:
        session.rollback()
        return _detail_page(request, document, 422, extract_error=exc.message)
    except DocumentNotFoundError:
        return _deleted_meanwhile(request, session)
    if error is not None:
        session.refresh(document)
        return _detail_page(request, document, extract_error=error.message)
    return RedirectResponse(f"/inbox/{document_id}/nakijken", status_code=303)


@router.post("/inbox/uitlezen-alles")
def extract_all(
    request: Request,
    session: Session = Depends(get_session),
    storage: DocumentStorage = Depends(get_storage),
    extractor=Depends(get_extractor_dep),
):
    pending = list(reversed(list_documents(session, status="nieuw", limit=10_000)))  # oldest first
    batch, skipped = pending[:BATCH_LIMIT], len(pending) - BATCH_LIMIT
    results, left = [], max(skipped, 0)
    for index, document in enumerate(batch):
        name, doc_id = document.original_filename, document.id
        try:
            error = _extract_one(session, storage, extractor, doc_id)
        except ExtractionNotAllowedError as exc:
            session.rollback()
            error = exc
        except DocumentNotFoundError:
            session.rollback()  # deleted while the extractor was working: skip it
            results.append({"name": name, "id": doc_id, "ok": False, "message": DELETED_MESSAGE})
            continue
        results.append({"name": name, "id": doc_id, "ok": error is None,
                        "message": error.message if error else ""})
        if isinstance(error, (ExtractorUnavailableError, ExtractionRateLimitedError)):
            left += len(batch) - index - 1  # no point trying the rest
            break
    counts = count_by_status(session)
    documents = list_documents(session, limit=LIST_LIMIT + 1)
    return _render(
        request,
        "inbox/list.html",
        title="Inbox",
        documents=documents[:LIST_LIMIT],
        capped=len(documents) > LIST_LIMIT,
        limit=LIST_LIMIT,
        counts=counts,
        total=sum(counts.values()),
        status_filter="",
        statuses=DOCUMENT_STATUSES,
        results=[],
        extract_results=results,
        extract_left=left,
    )


# --- review page -----------------------------------------------------------------


def _parse_flags(raw: str | None) -> list[dict]:
    try:
        flags = json.loads(raw or "[]")
    except ValueError:
        return []
    return [f for f in flags if isinstance(f, dict) and f.get("reason")]


def _flag_key(field: str) -> str:
    """Flag field names map onto form field names: 'total_excl_cents' -> 'total_excl'."""
    return field.removesuffix("_cents").replace(".", "_")


def _group(flags: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for f in flags:
        grouped.setdefault(_flag_key(str(f.get("field", ""))), []).append(f)
    return grouped


def _values_from_extraction(session: Session, extraction) -> dict:
    values = {
        "supplier_name": extraction.supplier_name, "supplier_kvk": extraction.supplier_kvk,
        "supplier_btw_number": extraction.supplier_btw_number,
        "supplier_iban": extraction.supplier_iban,
        "supplier_address_line": extraction.supplier_address_line,
        "supplier_postal_code": extraction.supplier_postal_code,
        "supplier_city": extraction.supplier_city,
        "supplier_country": extraction.supplier_country,
        "invoice_number": extraction.invoice_number,
        "invoice_date": _date_text(extraction.invoice_date),
        "due_date": _date_text(extraction.due_date),
        "currency": extraction.currency,
        "exchange_rate": format_rate(extraction.exchange_rate_micro) if extraction.exchange_rate_micro else "",
        "shifted_vat_rate": _rate_text(extraction.shifted_vat_rate_bp),
        "total_excl": _amount_text(extraction.total_excl_cents),
        "total_vat": _amount_text(extraction.total_vat_cents),
        "total_incl": _amount_text(extraction.total_incl_cents),
        "totals_override": False,
    }
    values = {k: ("" if v is None else v) for k, v in values.items()}
    codes = {a.id: a.code for a in session.scalars(select(Account))}
    values["lines"] = [
        {
            "description": line.description or "",
            "amount_excl": _amount_text(line.amount_excl_cents),
            "vat_code": line.vat_code or "",
            "vat_amount": _amount_text(line.vat_amount_cents),
            "account_code": codes.get(line.account_id, ""),
            "source_text": line.source_text or "",
        }
        for line in extraction.lines
    ]
    return values


def _rate_text(rate_bp: int | None) -> str:
    """2100 -> '21', 650 -> '6,5'; blank falls back to the default shifted rate."""
    rate_bp = DEFAULT_SHIFTED_VAT_BP if rate_bp is None else rate_bp
    whole, rest = divmod(rate_bp, 100)
    return f"{whole},{rest:02d}".rstrip("0") if rest else str(whole)


def _ordered_accounts(session: Session, selected: set[str]) -> list[Account]:
    """Inkoop accounts, the ones in use (suggested) first, the rest by name.

    An account already chosen on a line stays listed even when it is not selectable at inkoop.
    """
    accounts = list(ledger.list_accounts_for(session, "purchase"))
    listed = {a.code for a in accounts}
    missing = selected - listed
    if missing:
        accounts += session.scalars(select(Account).where(Account.code.in_(missing)))
    accounts.sort(key=lambda a: (a.name.lower(), a.code))
    first = [a for a in accounts if a.code in selected]
    return first + [a for a in accounts if a.code not in selected]


def _lookups(session: Session, values: dict | None = None) -> dict:
    selected = {ln["account_code"] for ln in (values or {}).get("lines", []) if ln["account_code"]}
    return {
        "accounts": _ordered_accounts(session, selected),
        "vat_codes": [v for v in ledger.list_vat_codes(session) if v.is_active],
    }


def _review_page(
    request: Request,
    session: Session,
    document,
    *,
    status: int = 200,
    values: dict | None = None,
    errors: list[str] | None = None,
    saved_notice: str | None = None,
    payment_choice: int | None = None,
):
    try:
        extraction = get_extraction(session, document.id)
    except ExtractionNotFoundError:
        extraction = None
    ctx: dict = {
        "title": "Nakijken",
        "document": document,
        "extraction": extraction,
        "errors": errors or [],
        "saved_notice": saved_notice,
        "no_account_hint": NO_ACCOUNT_HINT,
        "level_labels": LEVEL_LABELS,
        "field_labels": FIELD_LABELS,
    }
    if extraction is not None and extraction.status == "ok":
        header_flags = _parse_flags(extraction.flags_json)
        line_flags = [_group(_parse_flags(ln.flags_json)) for ln in extraction.lines]
        form_values = values if values is not None else _values_from_extraction(session, extraction)
        # Keep one flag list per submitted line; extra lines (added by the user) have none.
        line_flags += [{}] * (len(form_values["lines"]) - len(line_flags))
        counted = [f for f in header_flags if f.get("level") in LEVELS]
        counted += [f for g in line_flags for fl in g.values() for f in fl if f.get("level") in LEVELS]
        contact = session.get(Contact, extraction.contact_id) if extraction.contact_id else None
        payments = (
            reconcile.payment_candidates_for_extraction(session, extraction)
            if document.status != "geboekt" else []
        )
        ctx.update(
            values=form_values,
            flags=_group(header_flags),
            other_flags=[
                f for f in header_flags
                if _flag_key(str(f.get("field", ""))) not in (*HEADER_FIELDS, "totals", "kind")
            ],
            line_flags=line_flags,
            check_count=len(counted),
            contact=contact,
            payments=payments,
            payment_choice=payment_choice,
            **_lookups(session, form_values),
        )
    return _render(request, "inbox/review.html", status, **ctx)


@router.get("/inbox/{document_id:int}/nakijken")
def review_page(
    request: Request,
    document_id: int,
    melding: str = "",
    session: Session = Depends(get_session),
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    notice = {"geboekt": BOOKED_NEXT_MESSAGE, "opgeslagen": SAVED_MESSAGE}.get(melding)
    return _review_page(request, session, document, saved_notice=notice)


@router.get("/inbox/{document_id:int}/nakijken/regel")
def review_new_line(
    request: Request, document_id: int, session: Session = Depends(get_session)
):
    if _load(session, document_id) is None:
        return web.not_found_response(request)
    line = {k: "" for k in LINE_FIELDS}
    return web.templates.TemplateResponse(
        request,
        "inbox/_review_line.html",
        {"line": line, "flags": {}, "no_account_hint": NO_ACCOUNT_HINT, **_lookups(session)},
    )


def _review_input(form) -> ReviewInput:
    def text(name: str) -> str:
        return str(form.get(name) or "")

    columns = {f: [str(v) for v in form.getlist(f"line_{f}")] for f in LINE_FIELDS}
    count = max((len(v) for v in columns.values()), default=0)
    lines = [
        ReviewLineInput(
            **{f: (columns[f][i] if i < len(columns[f]) else "") for f in LINE_FIELDS}
        )
        for i in range(count)
    ]
    data = {f: text(f) for f in HEADER_FIELDS}
    data["currency"] = data["currency"] or "EUR"
    data["kind"] = text("kind") or "invoice"
    return ReviewInput(**data, totals_override=bool(form.get("totals_override")), lines=lines)


@router.post("/inbox/{document_id:int}/nakijken")
async def review_save(
    request: Request, document_id: int, session: Session = Depends(get_session)
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    form = await request.form()
    data = _review_input(form)
    book = form.get("actie") == "boeken"
    finish = book or form.get("actie") == "klaar"
    try:
        save_review(session, document_id, data, finish=finish)
        session.commit()
    except ReviewValidationError as exc:
        session.rollback()
        values = asdict(data)
        return _review_page(request, session, document, status=422, values=values, errors=exc.messages)
    except ExtractionNotAllowedError as exc:
        session.rollback()
        return _review_page(request, session, document, status=422, errors=[exc.message])
    except ExtractionNotFoundError:
        session.rollback()
        return _review_page(request, session, document)
    except DocumentNotFoundError:
        return _deleted_meanwhile(request, session)
    if book:
        return _book_and_continue(request, session, document, _payment_id(form))
    if finish:
        return RedirectResponse("/inbox?melding=klaar", status_code=303)
    return RedirectResponse(f"/inbox/{document_id}/nakijken?melding=opgeslagen", status_code=303)


def _payment_id(form) -> int | None:
    raw = str(form.get("bank_transaction_id") or "")
    return int(raw) if raw.isdigit() else None


def _book_and_continue(request: Request, session: Session, document, payment_id: int | None = None):
    """The review is saved and committed; book it (and the chosen payment) and go to the next
    invoice to check. Invoice and payment are committed together or not at all."""
    try:
        invoice = book_extraction(session, document.id)
        entry_id = invoice.journal_entry_id
        if payment_id is not None:
            reconcile.book_payment_for_invoice(session, payment_id, invoice)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _review_page(
            request, session, document, status=422, errors=[exc.message], payment_choice=payment_id
        )
    next_id = next_document_to_review(session, document.id)
    if next_id is None:
        return RedirectResponse(f"/inkoop?melding=geboekt&boeking={entry_id}", status_code=303)
    return RedirectResponse(f"/inbox/{next_id}/nakijken?melding=geboekt", status_code=303)
