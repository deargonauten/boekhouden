"""Routes for /bank (bankrekeningen, bankafschriften importeren, transacties).

Thin handlers: parse input, call app.domain.bank, render. No bank logic lives here.
"""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app import web
from app.db import get_session
from app.domain.bank import accounts as bank_accounts
from app.domain.bank import service as bank_service
from app.domain.bank.parsers import BANK_LABELS, FORMAT_LABELS
from app.domain.bank.storage import BankFileStorage
from app.domain.bank.types import MAX_FILE_BYTES, BankImportError
from app.domain.errors import LedgerError
from app.domain.relations import format_iban
from app.models import Account
from app.models.bank import BankAccount, BankImportBatch

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

PER_PAGE = 50
CHUNK_BYTES = 1024 * 1024
TABS = ("transacties", "geschiedenis")
BANK_CHOICES = [(k, v) for k, v in BANK_LABELS.items() if k != "overig"] + [("overig", "Andere bank")]
# Glossary key per detected file format (info icons on the preview).
FORMAT_TERMS = {"camt053": "camt053", "mt940": "mt940", "csv": "csv_export"}
# 1210 Bank is a system account, hidden from the "selectable bij bank" lists, but it is the default
# grootboekrekening for a bankrekening (spec AC 2), so it must stay choosable.
DEFAULT_BANK_CODES = ("1210", "1220")
STORAGE_FAILED_CODE = "DOCUMENT_STORAGE_FAILED"

NO_ACCOUNT_MESSAGE = (
    "Kies eerst bij welke bankrekening dit bankafschrift hoort. "
    "Heb je nog geen bankrekening, voeg die dan eerst toe."
)
NO_FILE_MESSAGE = (
    "Je hebt nog geen bestand gekozen. Kies het bankafschrift dat je in het internetbankieren hebt gedownload."
)
FILE_MISSING_MESSAGE = "Het originele bestand ontbreekt op schijf. Herstel data/bank uit je back-up."
ALREADY_PROCESSED_MESSAGE = "Deze import is al verwerkt."

web.templates.env.filters["bank_datum"] = lambda v: v.strftime("%d-%m-%Y") if v else ""
web.templates.env.filters["bank_datum_tijd"] = lambda v: v.strftime("%d-%m-%Y %H:%M") if v else ""
web.templates.env.filters["bank_iban"] = lambda v: format_iban(v) if v else ""
web.templates.env.globals["BANK_LABELS"] = BANK_LABELS
web.templates.env.globals["FORMAT_LABELS"] = FORMAT_LABELS


def get_storage(request: Request) -> BankFileStorage:
    return BankFileStorage(request.app.state.settings.bank_dir)


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=status
    )


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _status_for(error: LedgerError) -> int:
    return 500 if error.code == STORAGE_FAILED_CODE else 422


def _to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# --- small read helpers (single lookups; the rules live in app.domain.bank) ----


def _get_bank_account(session: Session, bank_account_id: int) -> BankAccount | None:
    return session.get(BankAccount, bank_account_id)


def _get_batch(session: Session, batch_id: int) -> BankImportBatch | None:
    return session.get(BankImportBatch, batch_id)


def _has_imports(session: Session, bank_account_id: int) -> bool:
    """True when a finished import exists: IBAN and grootboekrekening are then locked."""
    return (
        session.scalar(
            select(BankImportBatch.id)
            .where(BankImportBatch.bank_account_id == bank_account_id, BankImportBatch.status == "afgerond")
            .limit(1)
        )
        is not None
    )


def _account_choices(session: Session, current_account_id: int | None = None) -> list[dict]:
    """Grootboekrekeningen that can hold a bankrekening: active, postable assets flagged for bank use.

    `taken_by` names the bankrekening that already uses it (such a choice is disabled in the form).
    """
    linked = {b.account_id: b.name for b in bank_accounts.list_bank_accounts(session)}
    rows = session.scalars(
        select(Account)
        .where(
            Account.type == "asset",
            Account.is_postable.is_(True),
            Account.is_active.is_(True),
            or_(Account.selectable_bank.is_(True), Account.code.in_(DEFAULT_BANK_CODES)),
        )
        .order_by(Account.code)
    ).all()
    return [
        {
            "id": a.id,
            "code": a.code,
            "name": a.name,
            "taken_by": linked.get(a.id) if a.id != current_account_id else None,
        }
        for a in rows
    ]


def _stats_cards(session: Session) -> list[dict]:
    stats = bank_service.bank_stats(session)
    last = stats.last_imported_at
    return [
        {
            "title": "Je rekeningen",
            "term": "bankrekening",
            "cells": [
                {"label": "Aantal bankrekeningen", "value": stats.account_count},
                {"label": "Transacties", "value": stats.transaction_count},
            ],
        },
        {
            "title": "Laatste import",
            "term": "bankafschrift",
            "cells": [
                {"label": "Laatst geïmporteerd", "value": last.strftime("%d-%m-%Y") if last else "Nog niet"},
            ],
        },
    ]


def _transactions_context(session: Session, q: str, rekening: int | None, batch: int | None, page: int) -> dict:
    result = bank_service.list_transactions(
        session, q=q or None, bank_account_id=rekening, batch_id=batch, page=page
    )
    names = {a.id: a.name for a in bank_accounts.list_bank_accounts(session)}
    return {"transactions": result, "account_names": names, "q": q, "rekening": rekening, "batch": batch}


def _index_context(
    session: Session, tab: str, q: str, rekening: int | None, batch: int | None, page: int
) -> dict:
    accounts = bank_accounts.list_bank_accounts(session)
    ctx = {
        "tab": tab,
        "q": q,
        "rekening": rekening,
        "batch": batch,
        "accounts": accounts,
        "has_accounts": bool(accounts),
        "stat_data": _stats_cards(session) if accounts else [],
    }
    names = {a.id: a.name for a in accounts}
    if tab == "geschiedenis":
        ctx["batches"] = bank_service.list_batches(session, page=page)
        ctx["account_names"] = names
    else:
        ctx.update(_transactions_context(session, q, rekening, batch, page))
    return ctx


async def _read_limited(upload: UploadFile) -> bytes:
    """Read at most limit + 1 bytes: enough for the domain to see the file is too large."""
    data = bytearray()
    while len(data) <= MAX_FILE_BYTES:
        chunk = await upload.read(min(CHUNK_BYTES, MAX_FILE_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


# --- overview ------------------------------------------------------------------


@router.get("/bank", response_class=HTMLResponse)
def bank_index(
    request: Request,
    tab: str = "transacties",
    q: str = "",
    rekening: str = "",
    importeren: str = "",
    page: int = 1,
    melding: str = "",
    session: Session = Depends(get_session),
):
    tab = tab if tab in TABS else "transacties"
    ctx = _index_context(session, tab, q.strip(), _to_int(rekening), _to_int(importeren), page)
    return _render(request, "bank/index.html", title="Bank", melding=melding, **ctx)


@router.get("/bank/transacties", response_class=HTMLResponse)
def bank_transactions(
    request: Request,
    q: str = "",
    rekening: str = "",
    importeren: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
):
    ctx = _transactions_context(session, q.strip(), _to_int(rekening), _to_int(importeren), page)
    return _render(request, "bank/_transactions.html", **ctx)


# --- bankrekeningen --------------------------------------------------------------


def _new_account_values(session: Session, bank: str = "") -> dict:
    suggested = bank_accounts.suggest_account(session)
    bank = bank if bank in BANK_LABELS else ""
    name = f"Zakelijke rekening {BANK_LABELS[bank]}" if bank and bank != "overig" else "Zakelijke rekening"
    return {"name": name, "iban": "", "bank": bank, "account_id": suggested.id if suggested else None}


def _account_form(request: Request, session: Session, *, bank_account=None, values=None, error=None, status=200):
    locked = False
    if bank_account is not None:
        locked = _has_imports(session, bank_account.id)
    return _render(
        request,
        "bank/account_form.html",
        status,
        title="Bankrekening bewerken" if bank_account else "Bankrekening toevoegen",
        bank_account=bank_account,
        locked=locked,
        values=values,
        error=error,
        choices=_account_choices(session, bank_account.account_id if bank_account else None),
        bank_choices=BANK_CHOICES,
    )


@router.get("/bank/rekeningen/nieuw", response_class=HTMLResponse)
def account_new(request: Request, bank: str = "", session: Session = Depends(get_session)):
    return _account_form(request, session, values=_new_account_values(session, bank))


@router.post("/bank/rekeningen/nieuw", response_class=HTMLResponse)
async def account_create(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    bank = str(form.get("bank", "")).strip()
    name = str(form.get("name", "")).strip() or _new_account_values(session, bank)["name"]
    values = {
        "name": name,
        "iban": str(form.get("iban", "")).strip(),
        "bank": bank,
        "account_id": _to_int(form.get("account_id")),
    }
    try:
        if values["account_id"] is None:
            raise BankImportError("ACCOUNT_REQUIRED", "Kies bij welke grootboekrekening deze bankrekening hoort.")
        bank_accounts.create_bank_account(
            session, name, values["iban"], values["account_id"], bank or None
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _account_form(request, session, values=values, error=exc.message, status=422)
    return _see_other("/bank?melding=rekening_toegevoegd")


@router.get("/bank/rekeningen/{bank_account_id:int}/bewerken", response_class=HTMLResponse)
def account_edit(request: Request, bank_account_id: int, session: Session = Depends(get_session)):
    account = _get_bank_account(session, bank_account_id)
    if account is None:
        return web.not_found_response(request)
    values = {"name": account.name, "iban": format_iban(account.iban), "bank": account.bank or "", "account_id": account.account_id}
    return _account_form(request, session, bank_account=account, values=values)


@router.post("/bank/rekeningen/{bank_account_id:int}/bewerken", response_class=HTMLResponse)
async def account_update(request: Request, bank_account_id: int, session: Session = Depends(get_session)):
    account = _get_bank_account(session, bank_account_id)
    if account is None:
        return web.not_found_response(request)
    form = await request.form()
    values = {
        "name": str(form.get("name", "")).strip(),
        "iban": str(form.get("iban", account.iban)).strip(),
        "bank": str(form.get("bank", "")).strip(),
        "account_id": _to_int(form.get("account_id")) or account.account_id,
    }
    try:
        if form.get("actie") == "deactiveren":
            bank_accounts.deactivate(session, bank_account_id)
            session.commit()
            return _see_other("/bank?melding=rekening_uitgezet")
        locked = _has_imports(session, bank_account_id)
        bank_accounts.update_bank_account(
            session,
            bank_account_id,
            name=values["name"],
            bank=values["bank"] or None,
            iban=None if locked else values["iban"],
            account_id=None if locked else values["account_id"],
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _account_form(request, session, bank_account=account, values=values, error=exc.message, status=422)
    return _see_other("/bank?melding=rekening_opgeslagen")


# --- importeren -------------------------------------------------------------------


def _upload_page(request: Request, session: Session, *, rekening: int | None = None, error=None, status=200):
    accounts = [a for a in bank_accounts.list_bank_accounts(session) if a.is_active]
    return _render(
        request,
        "bank/upload.html",
        status,
        title="Bankafschrift importeren",
        accounts=accounts,
        rekening=rekening,
        error=error,
        max_mb=MAX_FILE_BYTES // (1024 * 1024),
    )


@router.get("/bank/importeren", response_class=HTMLResponse)
def import_form(request: Request, rekening: str = "", session: Session = Depends(get_session)):
    return _upload_page(request, session, rekening=_to_int(rekening))


@router.post("/bank/importeren", response_class=HTMLResponse)
async def import_start(
    request: Request,
    session: Session = Depends(get_session),
    storage: BankFileStorage = Depends(get_storage),
):
    form = await request.form()
    rekening = _to_int(form.get("bank_account_id"))
    upload = form.get("file")
    if rekening is None:
        return _upload_page(request, session, error=NO_ACCOUNT_MESSAGE, status=422)
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _upload_page(request, session, rekening=rekening, error=NO_FILE_MESSAGE, status=422)
    try:
        content = await _read_limited(upload)
        preview = bank_service.start_import(session, storage, rekening, upload.filename, content)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _upload_page(request, session, rekening=rekening, error=exc.message, status=_status_for(exc))
    return _see_other(f"/bank/importeren/{preview.batch_id}")


def _preview_page(request: Request, session: Session, storage, batch, *, error=None, status=200):
    preview = bank_service.preview_batch(session, storage, batch.id)
    account = _get_bank_account(session, batch.bank_account_id)
    return _render(
        request,
        "bank/preview.html",
        status,
        title="Controleer je bankafschrift",
        preview=preview,
        batch=batch,
        account=account,
        format_term=FORMAT_TERMS.get(batch.detected_format),
        error=error,
    )


@router.get("/bank/importeren/{batch_id:int}", response_class=HTMLResponse)
def import_detail(
    request: Request,
    batch_id: int,
    melding: str = "",
    session: Session = Depends(get_session),
    storage: BankFileStorage = Depends(get_storage),
):
    batch = _get_batch(session, batch_id)
    if batch is None:
        return web.not_found_response(request)
    if batch.status == "afgerond":
        account = _get_bank_account(session, batch.bank_account_id)
        return _render(
            request,
            "bank/result.html",
            title="Import klaar",
            batch=batch,
            account=account,
            already=melding == "al_verwerkt",
            already_message=ALREADY_PROCESSED_MESSAGE,
        )
    try:
        return _preview_page(request, session, storage, batch)
    except LedgerError as exc:
        return _upload_page(request, session, rekening=batch.bank_account_id, error=exc.message, status=_status_for(exc))


@router.post("/bank/importeren/{batch_id:int}/bevestigen", response_class=HTMLResponse)
async def import_confirm(
    request: Request,
    batch_id: int,
    session: Session = Depends(get_session),
    storage: BankFileStorage = Depends(get_storage),
):
    batch = _get_batch(session, batch_id)
    if batch is None:
        return web.not_found_response(request)
    form = await request.form()
    include = {n for n in (_to_int(v) for v in form.getlist("include_maybe")) if n is not None}
    try:
        result = bank_service.confirm_import(session, storage, batch_id, include)
        session.commit()
    except IntegrityError:
        # A concurrent confirm won: the transactions are already there.
        session.rollback()
        return _see_other(f"/bank/importeren/{batch_id}?melding=al_verwerkt")
    except LedgerError as exc:
        session.rollback()
        try:
            return _preview_page(request, session, storage, batch, error=exc.message, status=_status_for(exc))
        except LedgerError:
            return _upload_page(request, session, rekening=batch.bank_account_id, error=exc.message, status=_status_for(exc))
    suffix = "?melding=al_verwerkt" if result.already_processed else ""
    return _see_other(f"/bank/importeren/{batch_id}{suffix}")


@router.get("/bank/importeren/{batch_id:int}/bestand")
def import_file(
    request: Request,
    batch_id: int,
    session: Session = Depends(get_session),
    storage: BankFileStorage = Depends(get_storage),
):
    batch = _get_batch(session, batch_id)
    if batch is None:
        return web.not_found_response(request)
    path = storage.path_for(batch.sha256, batch.ext)
    if not path.is_file():
        logger.error("Bank file of batch %s is missing on disk: %s", batch.id, path)
        return _upload_page(request, session, rekening=batch.bank_account_id, error=FILE_MISSING_MESSAGE, status=500)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(batch.original_filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }
    return FileResponse(path, media_type="application/octet-stream", headers=headers)
