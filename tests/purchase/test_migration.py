"""Migration 0008: purchase_invoice, supplier_default and the source-link trigger."""

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
    """Fiscal year 2025 (period 1 open), a contact, a document and one posted entry."""
    db.execute("INSERT INTO fiscal_year(id, year, start_date, end_date, status) VALUES (1, 2025, '2025-01-01', '2025-12-31', 'open')")
    db.execute("INSERT INTO period(id, fiscal_year_id, number, start_date, end_date, status) VALUES (1, 1, 1, '2025-01-01', '2025-01-31', 'open')")
    j = one(db, "SELECT id FROM journal WHERE code='IK'")
    db.execute(
        "INSERT INTO journal_entry(id, journal_id, period_id, entry_number, booking_date, description, kind) "
        "VALUES (1, ?, 1, 'IK-2025-0001', '2025-01-10', 'x', 'normal')",
        (j,),
    )
    db.execute(
        "INSERT INTO contact(id, name, name_key, is_supplier, country, is_active, created_at, updated_at) "
        "VALUES (1, 'Bol', 'bol', 1, 'NL', 1, '2025-01-01', '2025-01-01')"
    )
    db.execute(
        "INSERT INTO document(id, sha256, original_filename, content_type, size_bytes, status, source, "
        "received_at, created_at, updated_at) VALUES (1, ?, 'f.pdf', 'application/pdf', 10, 'herkend', "
        "'upload', '2025-01-01', '2025-01-01', '2025-01-01')",
        ("a" * 64,),
    )


def insert_invoice(db, id_=1, document_id=1, entry_id=1, kind="invoice", total=12100, paid=0):
    db.execute(
        "INSERT INTO purchase_invoice(id, document_id, contact_id, journal_entry_id, invoice_number, "
        "invoice_number_key, invoice_date, kind, total_excl_cents, total_vat_cents, total_incl_cents, "
        "paid_cents, created_at) VALUES (?, ?, 1, ?, 'F-1', 'f-1', '2025-01-10', ?, 10000, 2100, ?, ?, "
        "'2025-01-10')",
        (id_, document_id, entry_id, kind, total, paid),
    )


def test_tables_created(db):
    assert {"purchase_invoice", "supplier_default"} <= tables(db)


def test_purchase_invoice_constraints(db):
    setup_entry(db)
    insert_invoice(db)
    assert one(db, "SELECT paid_cents FROM purchase_invoice") == 0
    with pytest.raises(sqlite3.IntegrityError):  # document unique
        insert_invoice(db, id_=2)
    for kw in [dict(kind="bon"), dict(total=0), dict(paid=-1)]:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM purchase_invoice")
            insert_invoice(db, id_=3, **kw)


def test_supplier_default_unique_per_contact_account(db):
    setup_entry(db)
    acc = one(db, "SELECT id FROM account WHERE code='4200'")
    db.execute(
        "INSERT INTO supplier_default(contact_id, account_id, vat_code, last_used_at) VALUES (1, ?, 'NL_21', '2025-01-01')",
        (acc,),
    )
    assert one(db, "SELECT use_count FROM supplier_default") == 1
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO supplier_default(contact_id, account_id, last_used_at) VALUES (1, ?, '2025-01-01')", (acc,)
        )


def test_source_link_can_be_set_once(db):
    setup_entry(db)
    with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
        db.execute("UPDATE journal_entry SET source_type='inkoopfactuur', description='y'")
    with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
        db.execute("UPDATE journal_entry SET source_type='inkoopfactuur'")  # source_id missing
    db.execute("UPDATE journal_entry SET source_type='inkoopfactuur', source_id=1")
    with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
        db.execute("UPDATE journal_entry SET source_id=2")
    with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
        db.execute("UPDATE journal_entry SET description='y'")


def test_downgrade_restores_strict_trigger(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0007_grootboek_verfijning")
    conn = sqlite3.connect(test_settings.database_path, isolation_level=None)
    try:
        assert not {"purchase_invoice", "supplier_default"} & tables(conn)
        setup_entry(conn)
        with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
            conn.execute("UPDATE journal_entry SET source_type='inkoopfactuur', source_id=1")
    finally:
        conn.close()
    command.upgrade(cfg, "head")
    command.check(cfg)
