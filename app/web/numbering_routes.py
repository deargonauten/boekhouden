"""Routes for /instellingen/factuurnummering. Parse input, call the numbering domain, render."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain.sales.numbering import (
    SEPARATORS,
    NumberingError,
    format_number,
    get_config,
    peek_next_seq,
    save_config,
)

router = APIRouter(include_in_schema=False)

URL = "/instellingen/factuurnummering"


def _render(request: Request, session: Session, *, values: dict, errors=(), status=200, flash=None) -> HTMLResponse:
    year = date.today().year
    return web.templates.TemplateResponse(
        request,
        "sales/numbering.html",
        web.page_context(
            request,
            title="Factuurnummering",
            values=values,
            errors=list(errors),
            flash=flash,
            year=year,
            separators=SEPARATORS,
        ),
        status_code=status,
    )


@router.get(URL)
def numbering_form(request: Request, opgeslagen: str = "", session: Session = Depends(get_session)):
    config = get_config(session)
    year = date.today().year
    values = {
        "separator": config.separator,
        "digits": config.digits,
        "continuous": config.continuous,
        "next_seq": peek_next_seq(session, year),
    }
    flash = "Factuurnummering opgeslagen." if opgeslagen == "1" else None
    return _render(request, session, values=values, flash=flash)


@router.post(URL)
def numbering_save(
    request: Request,
    separator: str = Form("-"),
    digits: str = Form("4"),
    continuous: str = Form(""),
    next_seq: str = Form(""),
    session: Session = Depends(get_session),
):
    year = date.today().year
    values = {"separator": separator, "digits": digits, "continuous": bool(continuous), "next_seq": next_seq}
    try:
        try:
            digits_n, next_n = int(digits.strip()), int(next_seq.strip())
        except ValueError:
            raise NumberingError("Vul bij het aantal cijfers en het volgende nummer een heel getal in, bijvoorbeeld 3 en 1.")
        save_config(
            session, separator=separator, digits=digits_n, continuous=bool(continuous),
            next_seq=next_n, year=year,
        )
        session.commit()
    except NumberingError as exc:
        session.rollback()
        return _render(request, session, values=values, errors=[exc.message], status=422)
    return RedirectResponse(f"{URL}?opgeslagen=1", status_code=303)
