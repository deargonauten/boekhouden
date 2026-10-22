"""Migration 0011: bank_match / bank_rule constraints and the append-only trigger."""

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=OFF")
    yield conn
    conn.close()


def insert_match(db, id_=1, amount=100, source="purchase_invoice"):
    db.execute(
        "INSERT INTO bank_match(id, bank_transaction_id, journal_entry_id, source, source_id, amount_cents, created_at) "
        "VALUES (?, 1, 1, ?, 1, ?, '2025-01-01')",
        (id_, source, amount),
    )


def insert_rule(db, iban="NL20INGB0001234567", needle=None, direction="af"):
    db.execute(
        "INSERT INTO bank_rule(name, counterparty_iban, description_contains, direction, account_id, created_at) "
        "VALUES ('r', ?, ?, ?, 1, '2025-01-01')",
        (iban, needle, direction),
    )


def test_tables_exist(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"bank_match", "bank_rule"} <= names


def test_match_constraints(db):
    insert_match(db)
    with pytest.raises(sqlite3.IntegrityError):
        insert_match(db, 2, amount=0)
    with pytest.raises(sqlite3.IntegrityError):
        insert_match(db, 3, source="onbekend")


def test_match_append_only(db):
    insert_match(db)
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("DELETE FROM bank_match")
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("UPDATE bank_match SET amount_cents = 5")
    db.execute("UPDATE bank_match SET reversed_at = '2025-02-01'")  # the one allowed change
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("UPDATE bank_match SET reversed_at = NULL")
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("UPDATE bank_match SET reversed_at = '2025-03-01'")


def test_rule_constraints(db):
    insert_rule(db)
    insert_rule(db, iban=None, needle="abonnement", direction="beide")
    with pytest.raises(sqlite3.IntegrityError):
        insert_rule(db, iban=None, needle=None)
    with pytest.raises(sqlite3.IntegrityError):
        insert_rule(db, direction="sideways")
    assert db.execute("SELECT is_active, use_count FROM bank_rule LIMIT 1").fetchone() == (1, 0)


def test_transaction_may_return_to_nieuw(db):
    """The existing bank_transaction trigger already allows status/journal_entry_id changes."""
    db.execute("INSERT INTO bank_account(id, name, iban, account_id, journal_id) VALUES (1, 'x', 'NL1', 1, 1)")
    db.execute(
        "INSERT INTO bank_import_batch(id, bank_account_id, status, original_filename, sha256, ext, size, detected_format, created_at) "
        "VALUES (1, 1, 'afgerond', 'x', 'x', 'csv', 1, 'csv', '2025-01-01')"
    )
    db.execute(
        "INSERT INTO bank_transaction(id, bank_account_id, import_batch_id, booking_date, amount_cents, dedupe_key, raw, status, created_at) "
        "VALUES (1, 1, 1, '2025-01-01', -100, 'k', '{}', 'geboekt', '2025-01-01')"
    )
    db.execute("UPDATE bank_transaction SET status='nieuw', journal_entry_id=NULL WHERE id=1")
    db.execute("UPDATE bank_transaction SET status='genegeerd' WHERE id=1")
    db.execute("UPDATE bank_transaction SET status='nieuw' WHERE id=1")


def test_downgrade_removes_tables(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0010_opening_balance")
    conn = sqlite3.connect(test_settings.database_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert "bank_match" not in names and "bank_rule" not in names
    assert "bank_match_no_update" not in names
