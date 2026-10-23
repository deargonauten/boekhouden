"""delete_document: unbooked inbox documents can be removed, booked ones never."""

import logging
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.domain.bank.storage import BankFileStorage
from app.domain.documents import (
    add_document,
    can_delete,
    delete_document,
    document_path,
    get_document,
    mark_booked,
    mark_recognized,
)
from app.domain.documents import service as doc_service
from app.domain.errors import (
    DocumentDeleteNotAllowedError,
    DocumentError,
    DocumentNotFoundError,
    DocumentStorageFailedError,
)
from app.domain.relations import ContactInput, create_contact
from app.models import (
    Account,
    Contact,
    Document,
    InvoiceExtraction,
    InvoiceExtractionLine,
    PurchaseInvoice,
    SupplierDefault,
)
from tests.documents.conftest import JPEG, PDF, storage  # noqa: F401

NOW = datetime(2025, 3, 11, 12, 0)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def pdf(n):
    return PDF + b"%" + str(n).encode() + b"\n"


def add(session, storage, n=0, name="factuur.pdf"):
    doc = add_document(session, storage, pdf(n), name).document
    session.commit()
    return doc


def add_extraction(session, doc, *, lines=3, contact=None):
    ex = InvoiceExtraction(
        document_id=doc.id, status="ok", extractor="test", contact_id=contact.id if contact else None,
        currency="EUR", created_at=NOW, updated_at=NOW,
    )
    session.add(ex)
    session.flush()
    for i in range(lines):
        session.add(InvoiceExtractionLine(extraction_id=ex.id, position=i, description=f"r{i}"))
    mark_recognized(session, doc.id)
    session.commit()
    return ex


def test_delete_nieuw_without_extraction(session, storage):
    doc = add(session, storage)
    path = document_path(storage, doc)
    assert path.is_file()
    delete_document(session, storage, doc.id)
    session.commit()
    assert count(session, Document) == 0
    assert not path.exists()
    assert not path.parent.exists()  # empty shard directory is cleaned up


def test_delete_herkend_with_extraction_and_lines(session, storage):
    keep = add(session, storage, 1, "keep.pdf")
    keep_ex = add_extraction(session, keep, lines=2)
    doc = add(session, storage, 2)
    add_extraction(session, doc, lines=3)
    path = document_path(storage, doc)
    assert count(session, InvoiceExtractionLine) == 5

    delete_document(session, storage, doc.id)
    session.commit()

    assert count(session, Document) == 1
    assert count(session, InvoiceExtraction) == 1
    assert count(session, InvoiceExtractionLine) == 2
    assert session.scalar(select(InvoiceExtraction.id)) == keep_ex.id
    assert not path.exists()
    assert document_path(storage, keep).is_file()


def test_booked_document_is_refused(session, storage, year2025, make_entry):
    doc = add(session, storage)
    add_extraction(session, doc)
    mark_booked(session, doc.id, make_entry().id)
    session.commit()
    with pytest.raises(DocumentDeleteNotAllowedError) as exc:
        delete_document(session, storage, doc.id)
    assert exc.value.code == "DOCUMENT_DELETE_NOT_ALLOWED"
    assert isinstance(exc.value, DocumentError)
    assert "Dit document is al geboekt en kan niet worden verwijderd" in exc.value.message
    assert "Stornoboeking maken" in exc.value.message
    assert count(session, Document) == 1
    assert count(session, InvoiceExtraction) == 1
    assert count(session, InvoiceExtractionLine) == 3
    assert document_path(storage, doc).is_file()
    assert can_delete(session, doc) is False


def test_journal_entry_link_alone_blocks(session, storage, year2025, make_entry):
    doc = add(session, storage)
    entry = make_entry()
    session.execute(
        text("UPDATE document SET journal_entry_id = :e WHERE id = :i"), {"e": entry.id, "i": doc.id}
    )
    session.commit()
    with pytest.raises(DocumentDeleteNotAllowedError):
        delete_document(session, storage, doc.id)
    assert document_path(storage, doc).is_file()


def test_purchase_invoice_blocks_even_when_status_is_herkend(session, storage, year2025, make_entry):
    doc = add(session, storage)
    add_extraction(session, doc)
    contact = create_contact(session, ContactInput(name="Bol B.V.", is_supplier=True))
    entry = make_entry()
    session.add(
        PurchaseInvoice(
            document_id=doc.id, contact_id=contact.id, journal_entry_id=entry.id,
            invoice_number="F-1", invoice_number_key="f-1", invoice_date=date(2025, 3, 10),
            kind="invoice", total_excl_cents=100, total_vat_cents=21, total_incl_cents=121,
            created_at=NOW,
        )
    )
    session.commit()
    assert get_document(session, doc.id).status == "herkend"
    assert can_delete(session, doc) is False
    with pytest.raises(DocumentDeleteNotAllowedError):
        delete_document(session, storage, doc.id)
    assert count(session, Document) == 1
    assert document_path(storage, doc).is_file()


def test_can_delete_true_for_unbooked(session, storage):
    doc = add(session, storage)
    assert can_delete(session, doc) is True
    add_extraction(session, doc)
    assert can_delete(session, doc) is True


def test_unknown_id(session, storage):
    with pytest.raises(DocumentNotFoundError):
        delete_document(session, storage, 999)


def test_file_shared_with_other_record_is_kept(session, storage, monkeypatch):
    doc = add(session, storage)
    path = document_path(storage, doc)
    monkeypatch.setattr(doc_service, "_file_shared", lambda *a, **k: True)
    delete_document(session, storage, doc.id)
    session.commit()
    assert count(session, Document) == 0
    assert path.is_file()


def test_file_shared_check_sees_other_row_with_same_sha(session, storage):
    doc = add(session, storage)
    path = document_path(storage, doc)
    session.execute(text("DROP INDEX uq_document_sha256"))
    session.execute(
        text(
            "INSERT INTO document (sha256, original_filename, content_type, size_bytes, status, source,"
            " received_at, created_at, updated_at) SELECT sha256, 'kopie.pdf', content_type, size_bytes,"
            " 'nieuw', 'upload', received_at, created_at, updated_at FROM document WHERE id = :i"
        ),
        {"i": doc.id},
    )
    session.commit()
    delete_document(session, storage, doc.id)
    session.commit()
    assert count(session, Document) == 1
    assert path.is_file()


def test_missing_file_still_deletes(session, storage, caplog):
    doc = add(session, storage)
    document_path(storage, doc).unlink()
    with caplog.at_level(logging.WARNING):
        delete_document(session, storage, doc.id)
    session.commit()
    assert count(session, Document) == 0
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_oserror_on_unlink_rolls_back(session, storage, monkeypatch):
    doc = add(session, storage)
    add_extraction(session, doc)
    path = document_path(storage, doc)

    def boom(self, *a, **k):
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "unlink", boom)
    with pytest.raises(DocumentStorageFailedError) as exc:
        delete_document(session, storage, doc.id)
    assert "Het bestand kon niet worden verwijderd" in exc.value.message
    assert count(session, Document) == 1
    assert count(session, InvoiceExtraction) == 1
    assert count(session, InvoiceExtractionLine) == 3
    assert path.is_file()


def test_service_never_commits(session, storage):
    doc = add(session, storage)
    add_extraction(session, doc)
    delete_document(session, storage, doc.id)
    session.rollback()
    assert count(session, Document) == 1
    assert count(session, InvoiceExtraction) == 1
    assert count(session, InvoiceExtractionLine) == 3


def test_other_tables_untouched(session, storage, acc):
    contact = create_contact(session, ContactInput(name="Bol B.V.", is_supplier=True))
    session.add(
        SupplierDefault(contact_id=contact.id, account_id=acc("4625"), use_count=1, last_used_at=NOW)
    )
    session.commit()
    doc = add(session, storage)
    add_extraction(session, doc, contact=contact)
    before = (count(session, SupplierDefault), count(session, Contact), count(session, Account))
    delete_document(session, storage, doc.id)
    session.commit()
    after = (count(session, SupplierDefault), count(session, Contact), count(session, Account))
    assert before == after
    assert after[0] == 1 and after[1] == 1


# --- storage.remove -----------------------------------------------------------------


def test_storage_remove_readonly_file(storage):
    stored = storage.write(PDF, "pdf")
    assert stored.path.is_file()
    assert (stored.path.stat().st_mode & 0o222) == 0
    assert storage.remove(stored.sha256, "pdf") is True
    assert not stored.path.exists()
    assert not stored.path.parent.exists()


def test_storage_remove_absent_returns_false(storage):
    assert storage.remove("a" * 64, "pdf") is False


def test_storage_remove_keeps_nonempty_shard(storage):
    a = storage.write(PDF, "pdf")
    sibling = a.path.parent / "other.txt"
    sibling.write_bytes(b"x")
    storage.remove(a.sha256, "pdf")
    assert sibling.exists()


@pytest.mark.parametrize(
    "sha,ext",
    [
        ("abc", "pdf"),
        ("g" * 64, "pdf"),
        ("../" + "a" * 61, "pdf"),
        ("A" * 64, "pdf"),
        ("a" * 64, "exe"),
        ("a" * 64, "../x"),
        ("a" * 64, ""),
    ],
)
def test_storage_remove_rejects_bad_input(storage, sha, ext):
    with pytest.raises(ValueError):
        storage.remove(sha, ext)


def test_storage_remove_only_exact_path(storage):
    stored = storage.write(PDF, "pdf")
    other = stored.path.with_suffix(".jpg")
    other.write_bytes(b"x")
    storage.remove(stored.sha256, "pdf")
    assert other.exists()


def test_bank_storage_remove_raises_and_keeps_file(tmp_path):
    bank = BankFileStorage(tmp_path / "bank")
    stored = bank.write(b"<xml/>", "xml")
    with pytest.raises(Exception):
        bank.remove(stored.sha256, "xml")
    assert stored.path.is_file()
