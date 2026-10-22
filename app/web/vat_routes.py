"""Routes for /instellingen/btw-codes. Parse input, call app.domain.vat, render.

No btw logic lives here; see app.domain.vat.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain import vat
from app.domain.errors import LedgerError, VAT_CODE_IN_LOCKED_PERIOD, VAT_CODE_IS_DEFAULT

router = APIRouter(include_in_schema=False)

CONFLICT_CODES = {VAT_CODE_IN_LOCKED_PERIOD, VAT_CODE_IS_DEFAULT}
DEFAULT_RATE = "21"


def _status_for(error: LedgerError) -> int:
    return 409 if error.code in CONFLICT_CODES else 400


def _format_rate(rate_bp: int) -> str:
    """2100 -> '21', 650 -> '6,5', 925 -> '9,25' (integer arithmetic only)."""
    whole, frac = divmod(rate_bp, 100)
    return f"{whole},{frac:02d}".rstrip("0").rstrip(",") if frac else str(whole)


def _suggestion(rate_text: str | None) -> tuple[str | None, str | None]:
    try:
        return vat.suggest_rubrieken(vat.parse_rate_bp(rate_text))
    except LedgerError:
        return vat.suggest_rubrieken(vat.parse_rate_bp(DEFAULT_RATE))


def _rubriek_options(side: str) -> list[tuple[str, str]]:
    catalogue = vat.SALES_RUBRIEKEN if side == "sales" else vat.PURCHASE_RUBRIEKEN
    return [(key, f"{key} - {label}") for key, label in catalogue.items()]


def _page(request: Request, session: Session, *, error=None, status=200, add_error=False,
          edit_code=None, values=None) -> HTMLResponse:
    sales, purchase = _suggestion(DEFAULT_RATE)
    form = values or {
        "code": "", "name": "", "rate": DEFAULT_RATE, "sales_rubriek": sales, "purchase_rubriek": purchase,
    }
    codes = vat.list_vat_codes_with_usage(session)
    if edit_code not in {c.code for c in codes}:
        edit_code = None  # unknown code: no modal to show the error in, so it goes in the page
    return web.templates.TemplateResponse(
        request,
        "vat/codes.html",
        web.page_context(
            request,
            title="Btw-codes",
            codes=codes,
            sales_options=_rubriek_options("sales"),
            purchase_options=_rubriek_options("purchase"),
            sales_labels=vat.SALES_RUBRIEKEN,
            purchase_labels=vat.PURCHASE_RUBRIEKEN,
            format_rate=_format_rate,
            error=error,
            add_error=add_error,
            edit_code=edit_code,
            values=form,
        ),
        status_code=status,
    )


def _see_other() -> RedirectResponse:
    return RedirectResponse("/instellingen/btw-codes", status_code=303)


@router.get("/instellingen/btw-codes")
def vat_codes_page(request: Request, session: Session = Depends(get_session)):
    return _page(request, session)


@router.get("/instellingen/btw-codes/voorstel")
def vat_rubriek_suggestion(request: Request, rate: str = ""):
    sales, purchase = _suggestion(rate)
    return web.templates.TemplateResponse(
        request,
        "vat/_rubriek_fields.html",
        {
            "sales_options": _rubriek_options("sales"),
            "purchase_options": _rubriek_options("purchase"),
            "sales_value": sales,
            "purchase_value": purchase,
            "prefix": "add",
        },
    )


@router.post("/instellingen/btw-codes")
def vat_code_add(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    rate: str = Form(""),
    sales_rubriek: str = Form(""),
    purchase_rubriek: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        vat.add_vat_code(
            session, code=code, name=name, rate_percent_text=rate,
            sales_rubriek=sales_rubriek, purchase_rubriek=purchase_rubriek,
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _page(
            request, session, error=exc.message, status=_status_for(exc), add_error=True,
            values={
                "code": code, "name": name, "rate": rate,
                "sales_rubriek": sales_rubriek, "purchase_rubriek": purchase_rubriek,
            },
        )
    return _see_other()


@router.post("/instellingen/btw-codes/{code}")
def vat_code_update(
    request: Request,
    code: str,
    name: str = Form(""),
    sales_rubriek: str = Form(""),
    purchase_rubriek: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        vat.update_vat_code(
            session, code, name=name, sales_rubriek=sales_rubriek, purchase_rubriek=purchase_rubriek
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _page(request, session, error=exc.message, status=_status_for(exc), edit_code=code)
    return _see_other()


@router.post("/instellingen/btw-codes/{code}/actief")
def vat_code_toggle(
    request: Request,
    code: str,
    active: str = Form("0"),
    session: Session = Depends(get_session),
):
    try:
        vat.set_vat_code_active(session, code, active == "1")
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _page(request, session, error=exc.message, status=_status_for(exc))
    return _see_other()
