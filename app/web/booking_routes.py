"""Routes for booking a nagekeken inkoopfactuur (preview + confirm).

Thin handlers: all rules live in app.domain.purchase. This module also registers a few
small template helpers so inbox/ledger screens (rendered by other routers) can show the
link to the inkoopfactuur and the learned hint without their handlers changing.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import SessionLocal, get_session
from app.domain.errors import LedgerError
from app.domain.purchase import (
    book_extraction,
    find_invoice_for_document,
    find_invoice_for_entry,
    prepare_booking,
    suggest_for_contact,
)

router = APIRouter(include_in_schema=False)

REVIEW_ANCHORS = {
    "supplier_name": "supplier_name",
    "invoice_number": "invoice_number",
    "invoice_date": "invoice_date",
    "currency": "currency",
    "total_excl": "total_excl",
    "total_vat": "total_vat",
    "total_incl": "total_incl",
}


def fix_link(document_id: int, error: LedgerError | None) -> str | None:
    """Where on the review screen the owner can fix this problem (None when it is not fixable there)."""
    field = getattr(error, "field", None)
    if not field:
        return None
    base = f"/inbox/{document_id}/nakijken"
    if field.startswith("line.") or field == "lines":
        return f"{base}#sec-lines"
    return f"{base}#{REVIEW_ANCHORS.get(field, field)}"


# --- template helpers (own short session: the owning handlers are not ours) ----------------------


def _purchase_invoice_for_document(request: Request, document_id: int):
    with SessionLocal(bind=request.app.state.engine) as session:
        return find_invoice_for_document(session, document_id)


def _purchase_document_for_entry(request: Request, entry_id: int):
    """The inkoopfactuur booked as this entry (its .document_id links back to the inbox), or None."""
    with SessionLocal(bind=request.app.state.engine) as session:
        return find_invoice_for_entry(session, entry_id)


def _learned_suggestion(request: Request, contact_id: int | None):
    if not contact_id:
        return None
    with SessionLocal(bind=request.app.state.engine) as session:
        return suggest_for_contact(session, contact_id)


web.templates.env.globals["purchase_invoice_for_document"] = _purchase_invoice_for_document
web.templates.env.globals["purchase_invoice_for_entry"] = _purchase_document_for_entry
web.templates.env.globals["learned_suggestion"] = _learned_suggestion


# --- handlers ------------------------------------------------------------------------------------


def _page(request: Request, preview, status: int = 200, error: LedgerError | None = None) -> HTMLResponse:
    shown = error or preview.error
    return web.templates.TemplateResponse(
        request,
        "inbox/book.html",
        web.page_context(
            request,
            title="Boeken",
            preview=preview,
            error_message=None if preview.needs_review else (shown.message if shown else None),
            fix_link=None if preview.needs_review else fix_link(preview.document_id, shown),
        ),
        status_code=status,
    )


def _preview_or_404(request: Request, session: Session, document_id: int):
    try:
        return prepare_booking(session, document_id), None
    except LedgerError as exc:
        if exc.code == "DOCUMENT_NOT_FOUND":
            return None, web.not_found_response(request)
        raise


@router.get("/inbox/{document_id:int}/boeken")
def booking_preview(request: Request, document_id: int, session: Session = Depends(get_session)):
    preview, missing = _preview_or_404(request, session, document_id)
    if missing is not None:
        return missing
    return _page(request, preview)


@router.post("/inbox/{document_id:int}/boeken")
def book_document(request: Request, document_id: int, session: Session = Depends(get_session)):
    try:
        book_extraction(session, document_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        if exc.code == "DOCUMENT_NOT_FOUND":
            return web.not_found_response(request)
        preview, _ = _preview_or_404(request, session, document_id)
        return _page(request, preview, 422, error=exc)
    return RedirectResponse("/inkoop?melding=geboekt", status_code=303)
