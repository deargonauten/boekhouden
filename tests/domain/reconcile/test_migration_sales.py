"""Migration 0013: bank_match accepts source 'sales_invoice', keeps rows, indexes and triggers."""

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config
from tests.domain.reconcile.test_migration import insert_match


def connect(test_settings):
    conn = sqlite3.connect(test_settings.database_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


@pytest.fixture
def cfg(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return alembic_config(test_settings)


def test_sales_source_allowed_and_others_still_refused(cfg, test_settings):
    command.upgrade(cfg, "head")
    db = connect(test_settings)
    insert_match(db, 1, source="sales_invoice")
    insert_match(db, 2, source="purchase_invoice")
    insert_match(db, 3, source="opening_item")
    with pytest.raises(sqlite3.IntegrityError):
        insert_match(db, 4, source="onbekend")
    with pytest.raises(sqlite3.IntegrityError):
        insert_match(db, 5, amount=0, source="sales_invoice")
    db.close()


def test_triggers_and_indexes_survive_the_rebuild(cfg, test_settings):
    command.upgrade(cfg, "head")
    db = connect(test_settings)
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert {"bank_match_no_update", "bank_match_no_delete", "ix_bank_match_source",
            "ix_bank_match_bank_transaction_id"} <= names
    assert "bank_match_old" not in names
    insert_match(db, 1, source="sales_invoice")
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("DELETE FROM bank_match")
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("UPDATE bank_match SET amount_cents = 5")
    db.execute("UPDATE bank_match SET reversed_at = '2025-02-01'")
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("UPDATE bank_match SET reversed_at = '2025-03-01'")
    db.close()


def test_existing_rows_are_copied(cfg, test_settings):
    command.upgrade(cfg, "0012_sales_invoices")
    db = connect(test_settings)
    insert_match(db, 7, amount=1234)
    db.execute("UPDATE bank_match SET reversed_at = '2025-02-01' WHERE id = 7")
    db.close()
    command.upgrade(cfg, "head")
    db = connect(test_settings)
    assert db.execute("SELECT id, amount_cents, source, reversed_at FROM bank_match").fetchall() == [
        (7, 1234, "purchase_invoice", "2025-02-01")
    ]
    db.close()


def test_downgrade_restores_check(cfg, test_settings):
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0012_sales_invoices")
    db = connect(test_settings)
    insert_match(db, 1)
    with pytest.raises(sqlite3.IntegrityError):
        insert_match(db, 2, source="sales_invoice")
    with pytest.raises(sqlite3.DatabaseError, match="onveranderlijk"):
        db.execute("DELETE FROM bank_match")
    db.close()


def test_downgrade_refused_with_sales_matches(cfg, test_settings):
    command.upgrade(cfg, "head")
    db = connect(test_settings)
    insert_match(db, 1, source="sales_invoice")
    db.close()
    with pytest.raises(RuntimeError, match="verkoopfacturen"):
        command.downgrade(cfg, "0012_sales_invoices")
