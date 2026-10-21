"""Routes for /relaties*. Parse input, call the relations service, render.

No relation logic lives here; see app.domain.relations.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain.relations import (
    ContactInput,
    RelationError,
    create_contact,
    format_iban,
    get_contact,
    list_contacts_page,
    set_contact_active,
    update_contact,
)

router = APIRouter(include_in_schema=False)

SOORT_TO_ROLE = {"klant": "customer", "leverancier": "supplier"}
PER_PAGE = 50
FORM_FIELDS = (
    "name", "kvk", "btw_number", "iban", "address_line", "postal_code",
    "city", "country", "email", "phone", "notes",
)

web.templates.env.filters["iban"] = lambda v: format_iban(v) if v else ""


def _status_for(error: RelationError) -> int:
    if error.code.startswith("DUPLICATE_"):
        return 409
    if error.code == "CONTACT_NOT_FOUND":
        return 404
    return 422


def _messages(error: RelationError) -> list[str]:
    return list(getattr(error, "messages", None) or [error.message])


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=status
    )


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _load(session: Session, contact_id: int):
    """The contact, or None when it does not exist."""
    try:
        return get_contact(session, contact_id)
    except RelationError as exc:
        if exc.code == "CONTACT_NOT_FOUND":
            return None
        raise


def _blank_values(**over) -> dict:
    values = {f: "" for f in FORM_FIELDS}
    values.update(country="NL", is_customer=False, is_supplier=True)
    values.update(over)
    return values


def _values_of(obj) -> dict:
    """Form values from a Contact or ContactInput (None becomes empty text)."""
    values = {f: getattr(obj, f) or "" for f in FORM_FIELDS}
    values.update(is_customer=bool(obj.is_customer), is_supplier=bool(obj.is_supplier))
    return values


def _form(request, *, values, errors=(), status=200, contact=None):
    return _render(
        request,
        "relations/form.html",
        status,
        title="Relatie bewerken" if contact else "Nieuwe relatie",
        values=values,
        errors=list(errors),
        contact=contact,
    )


@router.get("/relaties")
def contacts_list(
    request: Request,
    soort: str = "",
    q: str = "",
    gearchiveerd: str = "",
    page: str = "1",
    toegevoegd: int | None = None,
    bijgewerkt: int | None = None,
    session: Session = Depends(get_session),
):
    include_archived = gearchiveerd == "1"
    result = list_contacts_page(
        session,
        role=SOORT_TO_ROLE.get(soort),
        q=q.strip() or None,
        include_archived=include_archived,
        page=int(page) if page.strip().isdigit() else 1,
        per_page=PER_PAGE,
    )
    flash = None
    for contact_id, verb in ((toegevoegd, "toegevoegd"), (bijgewerkt, "bijgewerkt")):
        found = _load(session, contact_id) if contact_id else None
        if found:
            flash = f"Relatie {found.name} is {verb}."
    return _render(
        request,
        "relations/list.html",
        title="Relaties",
        contacts=result.items,
        page=result.page,
        per_page=result.per_page,
        total=result.total,
        soort=soort if soort in SOORT_TO_ROLE else "",
        q=q,
        include_archived=include_archived,
        flash=flash,
        filtered=bool(q.strip() or soort in SOORT_TO_ROLE or include_archived),
    )


@router.get("/relaties/nieuw")
def contact_new(request: Request, soort: str = "", naam: str = ""):
    # Supplier invoices are processed first, so "Leverancier" is the suggested role.
    customer = soort == "klant"
    return _form(
        request,
        values=_blank_values(name=naam, is_customer=customer, is_supplier=not customer),
    )


def _contact_input(
    name, is_customer, is_supplier, kvk, btw_number, iban, address_line,
    postal_code, city, country, email, phone, notes,
) -> ContactInput:
    return ContactInput(
        name=name,
        is_customer=is_customer == "1",
        is_supplier=is_supplier == "1",
        kvk=kvk,
        btw_number=btw_number,
        iban=iban,
        address_line=address_line,
        postal_code=postal_code,
        city=city,
        country=country,
        email=email,
        phone=phone,
        notes=notes,
    )


@router.post("/relaties/nieuw")
def contact_create(
    request: Request,
    name: str = Form(""),
    is_customer: str = Form(""),
    is_supplier: str = Form(""),
    kvk: str = Form(""),
    btw_number: str = Form(""),
    iban: str = Form(""),
    address_line: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form("NL"),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    data = _contact_input(
        name, is_customer, is_supplier, kvk, btw_number, iban, address_line,
        postal_code, city, country, email, phone, notes,
    )
    try:
        contact = create_contact(session, data)
        session.commit()
    except RelationError as exc:
        session.rollback()
        return _form(
            request, values=_values_of(data), errors=_messages(exc), status=_status_for(exc)
        )
    return _see_other(f"/relaties?toegevoegd={contact.id}")


@router.get("/relaties/{contact_id:int}/bewerken")
def contact_edit(request: Request, contact_id: int, session: Session = Depends(get_session)):
    contact = _load(session, contact_id)
    if contact is None:
        return web.not_found_response(request)
    return _form(request, values=_values_of(contact), contact=contact)


@router.post("/relaties/{contact_id:int}/bewerken")
def contact_update(
    request: Request,
    contact_id: int,
    name: str = Form(""),
    is_customer: str = Form(""),
    is_supplier: str = Form(""),
    kvk: str = Form(""),
    btw_number: str = Form(""),
    iban: str = Form(""),
    address_line: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form("NL"),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    if _load(session, contact_id) is None:
        return web.not_found_response(request)
    data = _contact_input(
        name, is_customer, is_supplier, kvk, btw_number, iban, address_line,
        postal_code, city, country, email, phone, notes,
    )
    try:
        update_contact(session, contact_id, data)
        session.commit()
    except RelationError as exc:
        session.rollback()
        if exc.code == "CONTACT_NOT_FOUND":
            return web.not_found_response(request)
        return _form(
            request,
            values=_values_of(data),
            errors=_messages(exc),
            status=_status_for(exc),
            contact=_load(session, contact_id),
        )
    return _see_other(f"/relaties?bijgewerkt={contact_id}")


def _toggle(request: Request, contact_id: int, session: Session, active: bool):
    if _load(session, contact_id) is None:
        return web.not_found_response(request)
    set_contact_active(session, contact_id, active)
    session.commit()
    return _see_other("/relaties")


@router.post("/relaties/{contact_id:int}/archiveren")
def contact_archive(request: Request, contact_id: int, session: Session = Depends(get_session)):
    return _toggle(request, contact_id, session, False)


@router.post("/relaties/{contact_id:int}/herstellen")
def contact_restore(request: Request, contact_id: int, session: Session = Depends(get_session)):
    return _toggle(request, contact_id, session, True)
