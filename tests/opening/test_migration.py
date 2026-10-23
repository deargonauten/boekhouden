"""Migration 0010: opening_item, its CHECK constraints and append-only triggers."""

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def setup_entry(db):
    db.execute("INSERT INTO fiscal_year(id, year, start_date, end_date, status) VALUES (1, 2025, '2025-01-01', '2025-12-31', 'open')")
    db.execute("INSERT INTO period(id, fiscal_year_id, number, start_date, end_date, status) VALUES (1, 1, 1, '2025-01-01', '2025-01-31', 'open')")
    j = one(db, "SELECT id FROM journal WHERE code='MEM'")
    db.execute(
        "INSERT INTO journal_entry(id, journal_id, period_id, entry_number, booking_date, description, kind) "
        "VALUES (1, ?, 1, 'MEM-2025-0001', '2025-01-01', 'Beginbalans 2025', 'opening')",
        (j,),
    )
    db.execute(
        "INSERT INTO contact(id, name, name_key, is_customer, country, is_active, created_at, updated_at) "
        "VALUES (1, 'Jansen', 'jansen', 1, 'NL', 1, '2025-01-01', '2025-01-01')"
    )


def insert_item(db, id_=1, side="debiteur", amount=10000, paid=None):
    cols = "id, fiscal_year_id, journal_entry_id, contact_id, side, invoice_number, invoice_number_key, invoice_date, amount_cents, created_at"
    vals = [id_, 1, 1, 1, side, "V-1", "v-1", "2024-12-01", amount, "2025-01-01"]
    if paid is not None:
        cols += ", paid_cents"
        vals.append(paid)
    db.execute(f"INSERT INTO opening_item({cols}) VALUES ({','.join('?' * len(vals))})", vals)


def test_table_and_head(db):
    assert "opening_item" in tables(db)
    assert one(db, "SELECT version_num FROM alembic_version") == "0019_invoice_numbering"


def test_constraints(db):
    setup_entry(db)
    insert_item(db)
    assert one(db, "SELECT paid_cents FROM opening_item") == 0
    for i, kw in enumerate([dict(side="klant"), dict(amount=0), dict(amount=-1), dict(paid=-1), dict(paid=10001)]):
        with pytest.raises(sqlite3.IntegrityError):
            insert_item(db, id_=10 + i, **kw)
    insert_item(db, id_=2, side="crediteur", paid=10000)


def test_foreign_keys(db):
    setup_entry(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO opening_item(fiscal_year_id, journal_entry_id, contact_id, side, invoice_number, "
            "invoice_number_key, invoice_date, amount_cents, created_at) "
            "VALUES (1, 1, 99, 'debiteur', 'X', 'x', '2024-12-01', 1, '2025-01-01')"
        )


def test_append_only_except_paid(db):
    setup_entry(db)
    insert_item(db)
    db.execute("UPDATE opening_item SET paid_cents = 500")
    assert one(db, "SELECT paid_cents FROM opening_item") == 500
    for sql in (
        "UPDATE opening_item SET amount_cents = 1",
        "UPDATE opening_item SET invoice_number = 'X'",
        "UPDATE opening_item SET due_date = '2025-02-01'",
        "DELETE FROM opening_item",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
            db.execute(sql)


def test_downgrade_and_upgrade_again(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0009_bank_import")
    conn = sqlite3.connect(test_settings.database_path)
    try:
        assert "opening_item" not in tables(conn)
        triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert not {"opening_item_no_update", "opening_item_no_delete"} & triggers
    finally:
        conn.close()
    command.upgrade(cfg, "head")
    command.check(cfg)
