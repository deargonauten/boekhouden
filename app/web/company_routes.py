"""Routes for /instellingen/bedrijfsgegevens. Parse input, call the company service, render.

No company logic lives here; see app.domain.company.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain.company import (
    CompanyError,
    CompanyInput,
    get_company_profile,
    save_company_profile,
)

router = APIRouter(include_in_schema=False)

URL = "/instellingen/bedrijfsgegevens"
FORM_FIELDS = (
    "legal_name", "trade_name", "legal_form", "address_line", "postal_code",
    "city", "country", "kvk", "btw_id", "iban", "email", "phone",
)


def _values_of(obj) -> dict:
    """Form values from a CompanyProfile or CompanyInput (None becomes empty text, defaults suggested)."""
    values = {f: getattr(obj, f, None) or "" for f in FORM_FIELDS}
    values["legal_form"] = values["legal_form"] or "eenmanszaak"
    values["country"] = values["country"] or "NL"
    return values


def _render(request: Request, session: Session, *, values, errors=(), status=200, flash=None) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request,
        "company/form.html",
        web.page_context(
            request,
            title="Bedrijfsgegevens",
            values=values,
            errors=list(errors),
            flash=flash,
            missing=get_company_profile(session).missing_for_invoice(),
        ),
        status_code=status,
    )


@router.get(URL)
def company_form(request: Request, opgeslagen: str = "", session: Session = Depends(get_session)):
    profile = get_company_profile(session)
    values = _values_of(profile)
    values["iban"] = profile.iban_display or ""
    flash = "Bedrijfsgegevens opgeslagen." if opgeslagen == "1" else None
    return _render(request, session, values=values, flash=flash)


@router.post(URL)
def company_save(
    request: Request,
    legal_name: str = Form(""),
    trade_name: str = Form(""),
    legal_form: str = Form(""),
    address_line: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    kvk: str = Form(""),
    btw_id: str = Form(""),
    iban: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    session: Session = Depends(get_session),
):
    data = CompanyInput(
        legal_name=legal_name, trade_name=trade_name, legal_form=legal_form,
        address_line=address_line, postal_code=postal_code, city=city, country=country,
        kvk=kvk, btw_id=btw_id, iban=iban, email=email, phone=phone,
    )
    try:
        save_company_profile(session, data)
        session.commit()
    except CompanyError as exc:
        session.rollback()
        return _render(
            request, session, values=_values_of(data),
            errors=getattr(exc, "messages", None) or [exc.message], status=422,
        )
    return RedirectResponse(f"{URL}?opgeslagen=1", status_code=303)
