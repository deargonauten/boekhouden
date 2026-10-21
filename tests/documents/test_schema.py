"""DB-level tests for the document table."""

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config

NOW = "2026-10-21 12:00:00"
SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def insert(db, **cols):
    cols = {
        "sha256": SHA_A,
        "original_filename": "f.pdf",
        "content_type": "application/pdf",
        "size_bytes": 10,
        "received_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        **cols,
    }
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO document ({names}) VALUES ({marks})", list(cols.values()))


def test_defaults(db):
    insert(db)
    assert db.execute("SELECT status, source, source_ref, journal_entry_id FROM document").fetchone() == (
        "nieuw",
        "upload",
        None,
        None,
    )


@pytest.mark.parametrize(
    "cols",
    [
        {"status": "kwijt"},
        {"source": "fax"},
        {"size_bytes": 0},
        {"sha256": "abc"},
        {"status": "geboekt"},  # booked needs a journal entry
    ],
)
def test_check_constraints(db, cols):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, **cols)


def test_unique_sha256(db):
    insert(db)
    with pytest.raises(sqlite3.IntegrityError):
        insert(db)
    insert(db, sha256=SHA_B)


def test_foreign_key_to_journal_entry(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, status="geboekt", journal_entry_id=999)


def test_expected_indexes(db):
    names = {r[1] for r in db.execute("PRAGMA index_list(document)")}
    assert {
        "uq_document_sha256",
        "ix_document_status",
        "ix_document_received_at",
        "ix_document_journal_entry_id",
    } <= names
