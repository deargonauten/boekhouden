"""Migration 0012: sales tables, constraints and the immutability triggers."""

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
    conn.execute("INSERT INTO contact(id, name, name_key, is_customer, country, is_active, created_at, updated_at)"
                 " VALUES (1, 'Klant', 'klant', 1, 'NL', 1, '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO fiscal_year(id, year, start_date, end_date, status) VALUES (1, 2026, '2026-01-01', '2026-12-31', 'open')")
    conn.execute("INSERT INTO period(id, fiscal_year_id, number, start_date, end_date, status) VALUES (1, 1, 1, '2026-01-01', '2026-01-31', 'open')")
    j = conn.execute("SELECT id FROM journal WHERE code='VK'").fetchone()[0]
    conn.execute(
        "INSERT INTO journal_entry(id, journal_id, period_id, entry_number, booking_date, description, kind) "
        "VALUES (1, ?, 1, 'VK-2026-0001', '2026-01-10', 'x', 'normal')", (j,))
    yield conn
    conn.close()


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def concept(db, id_=1, **kw):
    cols = dict(id=id_, kind="invoice", status="concept", contact_id=1, invoice_date="2026-01-10",
                payment_term_days=30, due_date="2026-02-09", created_at="2026-01-10", updated_at="2026-01-10")
    cols.update(kw)
    db.execute(
        f"INSERT INTO sales_invoice({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values())
    )


def add_line(db, invoice_id=1, id_=1):
    db.execute(
        "INSERT INTO sales_invoice_line(id, invoice_id, position, description, quantity_milli, unit_price_cents, vat_code)"
        " VALUES (?, ?, 0, 'x', 1000, 100, 'NL_21')", (id_, invoice_id))


FINAL = (
    "UPDATE sales_invoice SET status='definitief', number='2026-0001', number_year=2026, number_seq=1,"
    " journal_entry_id=1, pdf_sha256='a', seller_name='Ik', buyer_name='Klant', updated_at='2026-01-11'"
    " WHERE id=1"
)


def test_tables_and_contact_column(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sales_number_counter", "sales_invoice", "sales_invoice_line", "sales_invoice_vat",
            "sales_credit_application", "sales_reminder"} <= names
    db.execute("UPDATE contact SET payment_term_days = 14")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE contact SET payment_term_days = 366")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE contact SET payment_term_days = -1")


def test_constraints(db):
    concept(db)
    for kw in [dict(kind="bon"), dict(status="x"), dict(total_incl_cents=-1), dict(paid_cents=-1),
               dict(kind="invoice", credited_invoice_id=1)]:
        with pytest.raises(sqlite3.IntegrityError):
            concept(db, id_=9, **kw)
    with pytest.raises(sqlite3.IntegrityError):  # definitief needs a number, entry, pdf, snapshot
        concept(db, id_=9, status="definitief")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO sales_number_counter(year, last_number) VALUES (2026, -1)")


def test_number_is_unique_but_concepts_have_none(db):
    concept(db, id_=1)
    concept(db, id_=2)  # two concepts without number
    db.execute("UPDATE sales_invoice SET number='2026-0001', number_year=2026, number_seq=1 WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE sales_invoice SET number='2026-0001' WHERE id=2")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE sales_invoice SET number='2026-0002', number_year=2026, number_seq=1 WHERE id=2")


def test_finalize_transition_allowed_then_immutable(db):
    concept(db)
    add_line(db)
    db.execute(FINAL)  # concept -> definitief works
    for sql in [
        "UPDATE sales_invoice SET note='x'",
        "UPDATE sales_invoice SET total_incl_cents=5",
        "UPDATE sales_invoice SET status='concept'",
        "UPDATE sales_invoice SET buyer_name='Anders'",
        "UPDATE sales_invoice SET number='2026-0009'",
        "DELETE FROM sales_invoice",
        "UPDATE sales_invoice_line SET description='y'",
        "DELETE FROM sales_invoice_line",
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="definitieve factuur"):
            db.execute(sql)
    with pytest.raises(sqlite3.IntegrityError, match="definitieve factuur"):
        add_line(db, id_=2)
    with pytest.raises(sqlite3.IntegrityError, match="definitieve factuur"):
        db.execute("INSERT INTO sales_invoice_vat(invoice_id, vat_code, rate_bp, base_cents, vat_cents)"
                   " VALUES (1, 'NL_21', 2100, 100, 21)")
    # bank payments may still change paid_cents
    db.execute("UPDATE sales_invoice SET paid_cents=50, updated_at='2026-02-01'")
    assert one(db, "SELECT paid_cents FROM sales_invoice") == 50


def test_concept_is_freely_editable_and_deletable(db):
    concept(db)
    add_line(db)
    db.execute("UPDATE sales_invoice SET note='x', total_incl_cents=5")
    db.execute("UPDATE sales_invoice_line SET description='y'")
    db.execute("DELETE FROM sales_invoice_line")
    db.execute("DELETE FROM sales_invoice")


def test_vat_rows_of_concept_can_be_written(db):
    concept(db)
    db.execute("INSERT INTO sales_invoice_vat(invoice_id, vat_code, rate_bp, base_cents, vat_cents)"
               " VALUES (1, 'NL_21', 2100, 100, 21)")
    with pytest.raises(sqlite3.IntegrityError):  # primary key
        db.execute("INSERT INTO sales_invoice_vat(invoice_id, vat_code, rate_bp, base_cents, vat_cents)"
                   " VALUES (1, 'NL_21', 2100, 100, 21)")


def test_applications_and_reminders_are_append_only(db):
    concept(db, id_=1)
    concept(db, id_=2, kind="credit_note", credited_invoice_id=1)
    db.execute("INSERT INTO sales_credit_application(id, credit_note_id, invoice_id, amount_cents, created_at)"
               " VALUES (1, 2, 1, 100, '2026-01-01')")
    db.execute("INSERT INTO sales_reminder(id, invoice_id, level, reminder_date, new_due_date, open_cents,"
               " body_text, created_at) VALUES (1, 1, 1, '2026-03-01', '2026-03-15', 100, 't', '2026-03-01')")
    for sql in ["UPDATE sales_credit_application SET amount_cents=1", "DELETE FROM sales_credit_application",
                "UPDATE sales_reminder SET level=2", "DELETE FROM sales_reminder"]:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO sales_credit_application(credit_note_id, invoice_id, amount_cents, created_at)"
                   " VALUES (2, 1, 0, '2026-01-01')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO sales_reminder(invoice_id, level, reminder_date, new_due_date, open_cents,"
                   " body_text, created_at) VALUES (1, 4, '2026-03-01', '2026-03-15', 100, 't', '2026-03-01')")


def test_downgrade_and_upgrade_again(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0011_bank_reconciliation")
    conn = sqlite3.connect(test_settings.database_path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {n for n in names if n.startswith("sales_")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contact)")}
        assert "payment_term_days" not in cols
    finally:
        conn.close()
    command.upgrade(cfg, "head")
    command.check(cfg)
