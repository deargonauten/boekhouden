"""DB-level tests for invoice_extraction and invoice_extraction_line."""

import sqlite3

import pytest

from tests.conftest import migrate_to_head

NOW = "2026-10-21 12:00:00"


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    migrate_to_head(test_settings)
    conn = sqlite3.connect(test_settings.database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO document (sha256, original_filename, content_type, size_bytes, "
        "received_at, created_at, updated_at) VALUES (?, 'f.pdf', 'application/pdf', 10, ?, ?, ?)",
        ("a" * 64, NOW, NOW, NOW),
    )
    yield conn
    conn.close()


def insert_extraction(db, **cols):
    cols = {
        "document_id": 1,
        "status": "ok",
        "extractor": "fake",
        "created_at": NOW,
        "updated_at": NOW,
        **cols,
    }
    db.execute(
        f"INSERT INTO invoice_extraction ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        list(cols.values()),
    )


def test_defaults(db):
    insert_extraction(db)
    row = db.execute(
        "SELECT currency, flags_json, reviewed_at, contact_id, raw_json FROM invoice_extraction"
    ).fetchone()
    assert row == ("EUR", "[]", None, None, None)


def test_one_extraction_per_document(db):
    insert_extraction(db)
    with pytest.raises(sqlite3.IntegrityError):
        insert_extraction(db)


def test_status_check(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert_extraction(db, status="maybe")


def test_document_and_contact_must_exist(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert_extraction(db, document_id=99)
    with pytest.raises(sqlite3.IntegrityError):
        insert_extraction(db, contact_id=99)


def test_line_unique_position_and_foreign_keys(db):
    insert_extraction(db)
    db.execute("INSERT INTO invoice_extraction_line (extraction_id, position) VALUES (1, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO invoice_extraction_line (extraction_id, position) VALUES (1, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO invoice_extraction_line (extraction_id, position) VALUES (99, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO invoice_extraction_line (extraction_id, position, vat_code) "
            "VALUES (1, 1, 'NOPE')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO invoice_extraction_line (extraction_id, position, account_id) "
            "VALUES (1, 2, 99999)"
        )
    db.execute(
        "INSERT INTO invoice_extraction_line (extraction_id, position, vat_code, flags_json) "
        "VALUES (1, 3, 'NL_21', '[]')"
    )
