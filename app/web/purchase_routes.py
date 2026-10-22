"""Routes for /inkoop (Crediteuren). Parse input, call the purchase service, render.

No purchase logic lives here; see app.domain.purchase.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain.purchase import TABS, list_invoices, open_by_supplier

router = APIRouter(include_in_schema=False)

PER_PAGE = 50
DEFAULT_TAB = "open"


@router.get("/inkoop", response_class=HTMLResponse)
def inkoop(
    request: Request,
    tab: str = DEFAULT_TAB,
    q: str = "",
    page: int = 1,
    melding: str = "",
    boeking: int | None = None,
    session: Session = Depends(get_session),
):
    tab = "open" if tab not in TABS else tab
    q = q.strip()
    overview = open_by_supplier(session, q=q or None)
    invoices = list_invoices(session, q=q or None, tab="all", page=page, per_page=PER_PAGE) if tab == "all" else None
    has_any = list_invoices(session, per_page=1).total > 0  # any invoice at all, ignoring search
    return web.templates.TemplateResponse(
        request,
        "purchase/list.html",
        web.page_context(
            request,
            title="Inkoop",
            tab=tab,
            q=q,
            overview=overview,
            invoices=invoices,
            has_any=has_any,
            booked_notice=melding == "geboekt",
            booked_entry_id=boeking,
        ),
    )
