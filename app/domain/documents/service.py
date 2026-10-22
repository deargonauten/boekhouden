"""Document inbox service: ingest, query and status changes.

All functions flush but never commit; the caller owns the transaction. Files
that were written before a rollback stay on disk (content-addressed, reused on
the next upload of the same bytes). A stored file is only ever deleted by
`delete_document`, and only for an unbooked document (nieuw/herkend).
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Literal

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.documents import validation
from app.domain.documents.status import STATUS_LABELS, check_transition
from app.domain.documents.storage import DELETE_FAILED_MESSAGE, DocumentStorage
from app.domain.errors import (
    DocumentDeleteNotAllowedError,
    DocumentNotFoundError,
    DocumentStorageFailedError,
)
from app.models import Document, InvoiceExtraction, InvoiceExtractionLine, JournalEntry

logger = logging.getLogger(__name__)

DOCUMENT_SOURCES = ("upload", "email")


@dataclass(frozen=True)
class AddResult:
    document: Document
    outcome: Literal["created", "duplicate"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _find_by_sha256(session: Session, sha256: str) -> Document | None:
    return session.scalar(select(Document).where(Document.sha256 == sha256))


def _read_bytes(content: bytes | BinaryIO) -> bytes:
    if isinstance(content, (bytes, bytearray, memoryview)):
        return bytes(content)
    # Never read more than the limit + 1 sentinel byte into memory.
    return content.read(validation.MAX_DOCUMENT_BYTES + 1)


def add_document(
    session: Session,
    storage: DocumentStorage,
    content: bytes | BinaryIO,
    filename: str,
    *,
    source: str = "upload",
    source_ref: str | None = None,
    received_at: datetime | None = None,
) -> AddResult:
    """Validate, store and register a document; identical bytes give `duplicate`."""
    if source not in DOCUMENT_SOURCES:
        raise ValueError(f"unknown document source: {source!r}")
    data = _read_bytes(content)
    validation.check_size(len(data))  # empty -> too large
    detected = validation.sniff_type(data)  # then type

    sha256 = hashlib.sha256(data).hexdigest()
    existing = _find_by_sha256(session, sha256)
    if existing is not None:
        return AddResult(existing, "duplicate")

    storage.write(data, detected.ext)

    now = _now()
    document = Document(
        sha256=sha256,
        original_filename=validation.sanitize_filename(filename, detected.ext),
        content_type=detected.content_type,
        size_bytes=len(data),
        status="nieuw",
        source=source,
        source_ref=source_ref,
        received_at=received_at or now,
        created_at=now,
        updated_at=now,
    )
    # pysqlite only opens a transaction on DML, so a SAVEPOINT taken first would be
    # the outermost transaction and its RELEASE would commit. A no-op write makes
    # sure the caller's transaction is open, so the service never commits.
    session.execute(update(Document).where(Document.id.is_(None)).values(status=Document.status))
    try:
        with session.begin_nested():
            session.add(document)
    except IntegrityError:
        winner = _find_by_sha256(session, sha256)
        if winner is None:
            raise
        return AddResult(winner, "duplicate")
    return AddResult(document, "created")


def get_document(session: Session, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNotFoundError(
            "Dit document bestaat niet. Ga terug naar je inbox en kies een document uit de lijst."
        )
    return document


def list_documents(
    session: Session, *, status: str | None = None, limit: int = 500
) -> list[Document]:
    stmt = select(Document)
    if status is not None:
        stmt = stmt.where(Document.status == status)
    stmt = stmt.order_by(Document.received_at.desc(), Document.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def count_by_status(session: Session) -> dict[str, int]:
    counts = dict.fromkeys(STATUS_LABELS, 0)
    for status, n in session.execute(
        select(Document.status, func.count()).group_by(Document.status)
    ):
        counts[status] = n
    return counts


def document_path(storage: DocumentStorage, document: Document) -> Path:
    return storage.path_for(document.sha256, _ext(document))


def open_document(storage: DocumentStorage, document: Document) -> BinaryIO:
    return storage.open(document.sha256, _ext(document))


_EXT_BY_TYPE = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def _ext(document: Document) -> str:
    return _EXT_BY_TYPE[document.content_type]


def mark_recognized(session: Session, document_id: int) -> Document:
    """nieuw -> herkend."""
    document = get_document(session, document_id)
    check_transition(document.status, "herkend")
    document.status = "herkend"
    document.updated_at = _now()
    session.flush()
    return document


def mark_booked(session: Session, document_id: int, journal_entry_id: int) -> Document:
    """nieuw|herkend -> geboekt, linked to the booking."""
    document = get_document(session, document_id)
    check_transition(document.status, "geboekt")
    if session.get(JournalEntry, journal_entry_id) is None:
        raise DocumentNotFoundError("Deze boeking bestaat niet. Kies een bestaande boeking.")
    document.status = "geboekt"
    document.journal_entry_id = journal_entry_id
    document.updated_at = _now()
    session.flush()
    return document


DELETE_NOT_ALLOWED_MESSAGE = (
    "Dit document is al geboekt en kan niet worden verwijderd, want het hoort bij je "
    "administratie (bewaarplicht). Klopt de boeking niet? Maak dan een stornoboeking: "
    "open de boeking en kies 'Stornoboeking maken'. Het document blijft dan bij de boeking bewaard."
)

DELETABLE_STATUSES = ("nieuw", "herkend")


def _has_purchase_invoice(session: Session, document_id: int) -> bool:
    from app.models import PurchaseInvoice  # late: purchase builds on documents

    return bool(
        session.scalar(select(exists().where(PurchaseInvoice.document_id == document_id)))
    )


def can_delete(session: Session, document: Document) -> bool:
    """True while the document is not part of the administration.

    Extend this check when a future feature links a document to something else
    (e.g. bank reconciliation): `delete_document` relies on it.
    """
    return (
        document.status in DELETABLE_STATUSES
        and document.journal_entry_id is None
        and not _has_purchase_invoice(session, document.id)
    )


def _file_shared(session: Session, sha256: str, content_type: str, document_id: int) -> bool:
    """Does another document row still point at the same stored file?"""
    return bool(
        session.scalar(
            select(
                exists().where(
                    Document.sha256 == sha256,
                    Document.content_type == content_type,
                    Document.id != document_id,
                )
            )
        )
    )


def delete_document(session: Session, storage: DocumentStorage, document_id: int) -> None:
    """Really delete an unbooked document: extraction lines, extraction, row, then the file.

    Never commits. Raises DocumentNotFoundError, DocumentDeleteNotAllowedError (booked,
    nothing changed) or DocumentStorageFailedError (file could not be removed; the session
    is rolled back so the database is unchanged). supplier_default and contacts stay.
    """
    document = session.get(Document, document_id, populate_existing=True)  # fresh data
    if document is None:
        raise DocumentNotFoundError(
            "Dit document bestaat niet. Ga terug naar je inbox en kies een document uit de lijst."
        )
    if not can_delete(session, document):
        raise DocumentDeleteNotAllowedError(DELETE_NOT_ALLOWED_MESSAGE)

    sha256, ext, doc_id = document.sha256, _ext(document), document.id
    content_type = document.content_type
    extraction_ids = select(InvoiceExtraction.id).where(InvoiceExtraction.document_id == doc_id)
    session.execute(
        delete(InvoiceExtractionLine).where(InvoiceExtractionLine.extraction_id.in_(extraction_ids))
    )
    session.execute(delete(InvoiceExtraction).where(InvoiceExtraction.document_id == doc_id))
    session.execute(delete(Document).where(Document.id == doc_id))
    session.flush()  # takes the SQLite write lock: no insert can slip in before the unlink

    try:
        if _file_shared(session, sha256, content_type, doc_id):
            return
        if not storage.remove(sha256, ext):
            logger.warning("Document %s: file %s.%s was already missing on disk", doc_id, sha256, ext)
    except OSError as exc:
        session.rollback()
        logger.exception("Could not remove file of document %s", doc_id)
        raise DocumentStorageFailedError(DELETE_FAILED_MESSAGE) from exc
