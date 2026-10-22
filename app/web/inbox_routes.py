"""Routes for /inbox*. Parse the upload, call the documents service, render.

No validation or storage logic lives here; see app.domain.documents.
"""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app import web
from app.db import get_session
from app.domain.documents import (
    STATUS_LABELS,
    DocumentError,
    DocumentStorage,
    add_document,
    can_delete,
    count_by_status,
    delete_document,
    document_path,
    get_document,
    list_documents,
    validation,
)
from app.domain.documents.service import DELETE_NOT_ALLOWED_MESSAGE

DOCUMENT_STATUSES = tuple(STATUS_LABELS)  # nieuw, herkend, geboekt
format_size = validation.format_size

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

LIST_LIMIT = 500
CHUNK_BYTES = 1024 * 1024
NO_FILE_MESSAGE = (
    "Je hebt nog geen bestand gekozen. Kies een PDF of foto van je factuur of bon."
)
FILE_MISSING_MESSAGE = (
    "Het bestand ontbreekt op schijf. Herstel data/documents uit je back-up."
)
STORAGE_FAILED_CODE = "DOCUMENT_STORAGE_FAILED"
SOURCE_LABELS = {"upload": "Upload", "email": "E-mail"}

web.templates.env.filters["datum_tijd"] = lambda v: v.strftime("%d-%m-%Y %H:%M")
web.templates.env.filters["bestandsgrootte"] = format_size
web.templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
web.templates.env.globals["SOURCE_LABELS"] = SOURCE_LABELS
web.templates.env.globals["kind_label"] = lambda ct: "PDF" if ct == "application/pdf" else "Foto"


def get_storage(request: Request) -> DocumentStorage:
    return DocumentStorage(request.app.state.settings.documents_dir)


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, **ctx), status_code=status
    )


def _list_page(
    request: Request, session: Session, *, status_filter: str = "", results=(), status: int = 200
):
    status_filter = status_filter if status_filter in DOCUMENT_STATUSES else ""
    counts = count_by_status(session)
    # Fetch one extra row to know whether the list is capped.
    documents = list_documents(session, status=status_filter or None, limit=LIST_LIMIT + 1)
    capped = len(documents) > LIST_LIMIT
    return _render(
        request,
        "inbox/list.html",
        status,
        title="Inbox",
        documents=documents[:LIST_LIMIT],
        capped=capped,
        limit=LIST_LIMIT,
        counts=counts,
        total=sum(counts.values()),
        status_filter=status_filter,
        statuses=DOCUMENT_STATUSES,
        results=list(results),
    )


async def _read_limited(upload: UploadFile) -> bytes:
    """Read at most limit + 1 bytes: enough for the domain to see the file is too large."""
    limit = validation.MAX_DOCUMENT_BYTES
    data = bytearray()
    while len(data) <= limit:
        chunk = await upload.read(min(CHUNK_BYTES, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


@router.get("/inbox")
def inbox(request: Request, status: str = "", session: Session = Depends(get_session)):
    return _list_page(request, session, status_filter=status)


@router.post("/inbox/upload")
async def inbox_upload(
    request: Request,
    session: Session = Depends(get_session),
    storage: DocumentStorage = Depends(get_storage),
):
    form = await request.form()
    uploads = [f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename]
    if not uploads:
        results = [{"kind": "error", "name": "", "message": NO_FILE_MESSAGE}]
        return _list_page(request, session, results=results, status=422)

    results = []
    for upload in uploads:
        name = upload.filename
        try:
            data = await _read_limited(upload)
            result = add_document(session, storage, data, name)
            session.commit()
        except DocumentError as exc:
            session.rollback()
            results.append(
                {"kind": "error", "name": name, "message": exc.message, "code": exc.code}
            )
            continue
        document = result.document
        results.append(
            {
                "kind": result.outcome,
                "name": name,
                "document": document,
                "status_label": STATUS_LABELS[document.status],
            }
        )

    kinds = {r["kind"] for r in results}
    if kinds == {"error"}:
        # 500 only when every file failed because nothing could be written.
        all_storage = all(r.get("code") == STORAGE_FAILED_CODE for r in results)
        return _list_page(request, session, results=results, status=500 if all_storage else 422)
    return _list_page(request, session, results=results)


def _load(session: Session, document_id: int):
    try:
        return get_document(session, document_id)
    except DocumentError as exc:
        if exc.code == "DOCUMENT_NOT_FOUND":
            return None
        raise


@router.get("/inbox/{document_id:int}")
def document_detail(
    request: Request, document_id: int, session: Session = Depends(get_session)
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    if web.is_drawer_request(request, "inbox-drawer"):
        return _render(
            request,
            "inbox/_detail_body.html",
            document=document,
            status_label=STATUS_LABELS[document.status],
            in_drawer=True,
        )
    return _render(
        request,
        "inbox/detail.html",
        title=document.original_filename,
        document=document,
        status_label=STATUS_LABELS[document.status],
    )


@router.get("/inbox/{document_id:int}/bestand")
def document_file(
    request: Request,
    document_id: int,
    session: Session = Depends(get_session),
    storage: DocumentStorage = Depends(get_storage),
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    path = document_path(storage, document)
    if not path.is_file():
        logger.error("Document %s is missing on disk: %s", document.id, path)
        return _render(
            request,
            "inbox/missing.html",
            500,
            title="Bestand ontbreekt",
            message=FILE_MISSING_MESSAGE,
            document=document,
        )
    headers = {
        "Content-Disposition": (
            f"inline; filename*=UTF-8''{quote(document.original_filename, safe='')}"
        ),
        "X-Content-Type-Options": "nosniff",
    }
    # A sandbox CSP stops Chrome/Safari from rendering PDFs, so only images get it.
    if document.content_type != "application/pdf":
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(path, media_type=document.content_type, headers=headers)


def _delete_page(request: Request, session: Session, document, status: int = 200, error=None):
    return _render(
        request,
        "inbox/delete.html",
        status,
        title="Document verwijderen?",
        document=document,
        can_delete=can_delete(session, document),
        error_message=error,
        not_allowed_message=DELETE_NOT_ALLOWED_MESSAGE,
    )


@router.get("/inbox/{document_id:int}/verwijderen")
def document_delete_confirm(
    request: Request, document_id: int, session: Session = Depends(get_session)
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    return _delete_page(request, session, document)


@router.post("/inbox/{document_id:int}/verwijderen")
def document_delete(
    request: Request,
    document_id: int,
    session: Session = Depends(get_session),
    storage: DocumentStorage = Depends(get_storage),
):
    document = _load(session, document_id)
    if document is None:
        return web.not_found_response(request)
    try:
        delete_document(session, storage, document_id)
        session.commit()
    except DocumentError as exc:
        session.rollback()
        if exc.code == "DOCUMENT_NOT_FOUND":
            return web.not_found_response(request)
        failed = exc.code == STORAGE_FAILED_CODE
        return _delete_page(request, session, document, 500 if failed else 409, error=exc.message)
    return RedirectResponse("/inbox?melding=verwijderd", status_code=303)
