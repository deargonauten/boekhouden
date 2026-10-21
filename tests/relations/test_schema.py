"""DB-level tests for the contact table: constraints and partial unique indexes."""

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config

NOW = "2026-10-21 12:00:00"


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def insert(db, name="X", customer=0, supplier=1, **cols):
    cols = {
        "name": name,
        "name_key": name.lower(),
        "is_customer": customer,
        "is_supplier": supplier,
        "created_at": NOW,
        "updated_at": NOW,
        **cols,
    }
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO contact ({names}) VALUES ({marks})", list(cols.values()))


def test_defaults(db):
    insert(db)
    row = db.execute("SELECT country, is_active, kvk FROM contact").fetchone()
    assert row == ("NL", 1, None)


def test_role_check(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, customer=0, supplier=0)


@pytest.mark.parametrize("kvk", ["1234567", "123456789", "1234567a", ""])
def test_kvk_check(db, kvk):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, kvk=kvk)


def test_country_check(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, country="NLD")


@pytest.mark.parametrize(
    "col,a,b",
    [("kvk", "12345678", "12345678"), ("btw_number", "NL123456789B01", "NL123456789B01"), ("iban", "NL91ABNA0417164300", "NL91ABNA0417164300")],
)
def test_unique_partial_indexes(db, col, a, b):
    insert(db, name="A", **{col: a})
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, name="B", **{col: b})
    # Multiple NULLs are fine.
    insert(db, name="C")
    insert(db, name="D")


def test_unique_applies_to_archived_too(db):
    insert(db, name="A", kvk="12345678", is_active=0)
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, name="B", kvk="12345678")


def test_indexes_exist(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"uq_contact_kvk", "uq_contact_btw_number", "uq_contact_iban", "ix_contact_name_key", "ix_contact_is_active"} <= names


def test_downgrade_drops_table(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002_core_ledger")
    conn = sqlite3.connect(test_settings.database_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "contact" not in tables
