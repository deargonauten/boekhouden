import hashlib
import io
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.domain.documents import service
from app.domain.documents import (
    AddResult,
    add_document,
    count_by_status,
    document_path,
    get_document,
    list_documents,
    mark_booked,
    mark_recognized,
    open_document,
)
from app.domain.errors import (
    DocumentNotFoundError,
    EmptyFileError,
    InvalidStatusTransitionError,
    UnsupportedFileTypeError,
)
from app.models import Document
from tests.documents.conftest import JPEG, PDF, PNG


def rows(session):
    return session.scalar(select(func.count()).select_from(Document))


def files(storage):
    return [p for p in storage.root.rglob("*") if p.is_file()] if storage.root.exists() else []


def test_created_row_fields(session, storage):
    res = add_document(session, storage, PDF, "Factuur.pdf")
    assert isinstance(res, AddResult)
    assert res.outcome == "created"
    d = res.document
    assert d.sha256 == hashlib.sha256(PDF).hexdigest()
    assert d.size_bytes == len(PDF)
    assert d.content_type == "application/pdf"
    assert d.original_filename == "Factuur.pdf"
    assert d.status == "nieuw"
    assert d.source == "upload"
    assert d.source_ref is None
    assert d.journal_entry_id is None
    assert d.received_at is not None and d.created_at is not None
    assert document_path(storage, d).read_bytes() == PDF


def test_accepts_binary_stream(session, storage):
    res = add_document(session, storage, io.BytesIO(JPEG), "foto.jpeg")
    assert res.document.content_type == "image/jpeg"


def test_type_comes_from_content_not_filename(session, storage):
    d = add_document(session, storage, JPEG, "x.pdf").document
    assert d.content_type == "image/jpeg"
    assert document_path(storage, d).suffix == ".jpg"


def test_traversal_filename_is_sanitized(session, storage):
    d = add_document(session, storage, PDF, "../../x.pdf").document
    assert d.original_filename == "x.pdf"
    assert document_path(storage, d).parent.parent == storage.root


def test_email_source_fields(session, storage):
    when = datetime(2026, 1, 2, 3, 4)
    d = add_document(
        session, storage, PDF, "a.pdf", source="email", source_ref="<m@x>", received_at=when
    ).document
    assert (d.source, d.source_ref, d.received_at) == ("email", "<m@x>", when)


def test_unknown_source_rejected(session, storage):
    with pytest.raises(ValueError):
        add_document(session, storage, PDF, "a.pdf", source="fax")


def test_duplicate_returns_existing_and_stores_nothing(session, storage):
    first = add_document(session, storage, PDF, "a.pdf")
    second = add_document(session, storage, PDF, "other-name.pdf")
    assert second.outcome == "duplicate"
    assert second.document.id == first.document.id
    assert rows(session) == 1
    assert len(files(storage)) == 1


def test_race_integrity_error_becomes_duplicate(session, storage, monkeypatch):
    winner = add_document(session, storage, PDF, "a.pdf").document
    session.commit()
    real = service._find_by_sha256
    calls = []

    def blind_first(sess, sha):
        calls.append(sha)
        return None if len(calls) == 1 else real(sess, sha)

    monkeypatch.setattr(service, "_find_by_sha256", blind_first)
    res = add_document(session, storage, PDF, "b.pdf")
    assert res.outcome == "duplicate"
    assert res.document.id == winner.id
    assert rows(session) == 1
    assert len(files(storage)) == 1


@pytest.mark.parametrize(
    "content,exc", [(b"", EmptyFileError), (b"just some text", UnsupportedFileTypeError)]
)
def test_rejected_file_leaves_nothing(session, storage, content, exc):
    with pytest.raises(exc):
        add_document(session, storage, content, "x.pdf")
    assert rows(session) == 0
    assert files(storage) == []


def test_oversize_rejected(session, storage, monkeypatch):
    import app.domain.documents.validation as v

    monkeypatch.setattr(v, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(Exception) as exc:
        add_document(session, storage, PDF, "x.pdf")
    assert exc.value.code == "FILE_TOO_LARGE"
    assert rows(session) == 0


def test_service_does_not_commit(session, storage):
    add_document(session, storage, PDF, "a.pdf")
    session.rollback()
    assert rows(session) == 0
    # the orphan file stays and is reused by the next upload of the same bytes
    assert len(files(storage)) == 1
    assert add_document(session, storage, PDF, "a.pdf").outcome == "created"
    assert len(files(storage)) == 1


def test_get_document(session, storage):
    d = add_document(session, storage, PDF, "a.pdf").document
    assert get_document(session, d.id).id == d.id
    with pytest.raises(DocumentNotFoundError):
        get_document(session, 999)


def test_open_document(session, storage):
    d = add_document(session, storage, PDF, "a.pdf").document
    with open_document(storage, d) as f:
        assert f.read() == PDF


def test_list_ordering_filter_limit(session, storage):
    t = datetime(2026, 1, 1)
    a = add_document(session, storage, PDF, "a.pdf", received_at=t).document
    b = add_document(session, storage, JPEG, "b.jpg", received_at=t + timedelta(days=1)).document
    c = add_document(session, storage, PNG, "c.png", received_at=t + timedelta(days=1)).document
    assert [d.id for d in list_documents(session)] == [c.id, b.id, a.id]
    mark_recognized(session, a.id)
    assert [d.id for d in list_documents(session, status="herkend")] == [a.id]
    assert len(list_documents(session, limit=2)) == 2


def test_count_by_status_has_all_keys(session, storage):
    assert count_by_status(session) == {"nieuw": 0, "herkend": 0, "geboekt": 0}
    a = add_document(session, storage, PDF, "a.pdf").document
    add_document(session, storage, JPEG, "b.jpg")
    mark_recognized(session, a.id)
    assert count_by_status(session) == {"nieuw": 1, "herkend": 1, "geboekt": 0}


def test_mark_recognized_bumps_updated_at(session, storage):
    d = add_document(session, storage, PDF, "a.pdf").document
    d.updated_at = datetime(2020, 1, 1)
    session.flush()
    mark_recognized(session, d.id)
    assert d.status == "herkend"
    assert d.updated_at > datetime(2020, 1, 1)


def test_mark_booked_from_herkend_and_nieuw(session, storage, year2025, make_entry):
    e = make_entry()
    a = add_document(session, storage, PDF, "a.pdf").document
    b = add_document(session, storage, JPEG, "b.jpg").document
    mark_recognized(session, a.id)
    mark_booked(session, a.id, e.id)
    mark_booked(session, b.id, e.id)
    assert (a.status, a.journal_entry_id) == ("geboekt", e.id)
    assert (b.status, b.journal_entry_id) == ("geboekt", e.id)


def test_geboekt_is_final(session, storage, year2025, make_entry):
    e = make_entry()
    d = add_document(session, storage, PDF, "a.pdf").document
    mark_booked(session, d.id, e.id)
    for fn in (lambda: mark_recognized(session, d.id), lambda: mark_booked(session, d.id, e.id)):
        with pytest.raises(InvalidStatusTransitionError):
            fn()


def test_herkend_cannot_be_recognized_again(session, storage):
    d = add_document(session, storage, PDF, "a.pdf").document
    mark_recognized(session, d.id)
    with pytest.raises(InvalidStatusTransitionError):
        mark_recognized(session, d.id)


def test_mark_booked_requires_existing_entry(session, storage):
    d = add_document(session, storage, PDF, "a.pdf").document
    with pytest.raises(DocumentNotFoundError) as exc:
        mark_booked(session, d.id, 12345)
    assert exc.value.message == "Deze boeking bestaat niet. Kies een bestaande boeking."
    assert d.status == "nieuw"


def test_transitions_unknown_document(session):
    with pytest.raises(DocumentNotFoundError):
        mark_recognized(session, 1)


def test_no_delete_api():
    # deletion exists only as delete_document (unbooked documents, see test_delete.py)
    for name in ("remove_document", "remove"):
        assert not hasattr(service, name)
