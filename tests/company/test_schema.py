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
    yield conn
    conn.close()


def insert(db, **cols):
    cols = {"id": 1, "legal_name": "Jansen", "created_at": NOW, "updated_at": NOW, **cols}
    db.execute(
        f"INSERT INTO company_profile ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        list(cols.values()),
    )


def test_defaults(db):
    insert(db)
    row = db.execute("SELECT legal_form, country, kvk, btw_id FROM company_profile").fetchone()
    assert row == ("eenmanszaak", "NL", None, None)


def test_second_row_rejected(db):
    insert(db)
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, id=2)


def test_name_not_null(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, legal_name=None)


@pytest.mark.parametrize("kvk", ["1234567", "123456789", "1234567a", ""])
def test_kvk_check(db, kvk):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, kvk=kvk)


def test_kvk_ok(db):
    insert(db, kvk="12345678")


@pytest.mark.parametrize(
    "btw", ["NL123456789B1", "DE123456789B01", "NL12345678XB01", "nl123456789b01", "NL123456789B011"]
)
def test_btw_check(db, btw):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, btw_id=btw)


def test_btw_ok(db):
    insert(db, btw_id="NL123456789B01")


def test_legal_form_check(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, legal_form="bv")
    insert(db, legal_form="vof")


def test_country_check(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, country="NLD")
