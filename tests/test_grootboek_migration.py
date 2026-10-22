"""Migration 0007: rubrieken, system flags and 'selecteerbaar bij' backfill."""
import sqlite3

import pytest
from alembic import command

from app.seed.rgs_accounts import default_contexts
from app.seed.vat_rubrieken import SEED_VAT_ORDER, SEED_VAT_RUBRIEKEN
from tests.conftest import alembic_config


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path)
    yield conn
    conn.close()


@pytest.mark.parametrize(
    "type_, is_system, code, expected",
    [
        ("expense", False, "4210", (True, False, True)),
        ("expense", True, "4950", (False, False, False)),
        ("expense", True, "4999", (False, False, False)),
        ("revenue", False, "8010", (False, True, True)),
        ("revenue", True, "8000", (False, True, True)),
        ("asset", False, "0110", (True, False, True)),
        ("asset", False, "0100", (True, False, True)),
        ("asset", False, "0120", (True, False, True)),
        ("asset", False, "1220", (False, False, True)),
        ("asset", True, "1210", (False, False, False)),
        ("asset", True, "1300", (False, False, False)),
        ("asset", True, "0190", (False, False, False)),
        ("asset", True, "1230", (False, False, False)),
        ("equity", True, "2010", (False, False, True)),
        ("equity", True, "2030", (False, False, True)),
        ("equity", True, "2000", (False, False, False)),
        ("equity", True, "2900", (False, False, False)),
        ("liability", False, "3200", (False, False, True)),
        ("liability", True, "3100", (False, False, False)),
        ("liability", True, "3000", (False, False, False)),
        ("expense", False, "4777", (True, False, True)),
        ("liability", False, "3777", (False, False, True)),
    ],
)
def test_default_contexts(type_, is_system, code, expected):
    assert default_contexts(type_, is_system, code) == expected


@pytest.mark.parametrize(
    "code, flags",
    [
        ("4000", (1, 0, 1)),
        ("4210", (1, 0, 1)),
        ("4400", (1, 0, 1)),
        ("8000", (0, 1, 1)),
        ("8010", (0, 1, 1)),
        ("1210", (0, 0, 0)),
        ("1300", (0, 0, 0)),
        ("0110", (1, 0, 1)),
        ("2010", (0, 0, 1)),
        ("3200", (0, 0, 1)),
        ("3100", (0, 0, 0)),
        ("4950", (0, 0, 0)),
    ],
)
def test_seeded_account_flags(db, code, flags):
    row = db.execute(
        "SELECT selectable_purchase, selectable_sales, selectable_bank "
        "FROM account WHERE code=?",
        (code,),
    ).fetchone()
    assert row == flags


def test_vat_code_rubrieken_and_system(db):
    rows = {
        r[0]: r[1:]
        for r in db.execute(
            "SELECT code, sales_rubriek, purchase_rubriek, is_system FROM vat_code"
        )
    }
    assert set(rows) == set(SEED_VAT_ORDER)
    expected = {
        "GEEN": (None, None),
        "NL_21": ("1a", "5b"),
        "NL_9": ("1b", "5b"),
        "NL_0": ("1e", None),
        "VERLEGD": ("1e", "2a"),
        "EU_GOEDEREN": ("3b", "4b"),
        "EU_DIENSTEN": ("3b", "4b"),
        "EXPORT": ("3a", "4a"),
    }
    assert SEED_VAT_RUBRIEKEN == expected
    for code, (sales, purchase) in expected.items():
        assert rows[code] == (sales, purchase, 1)


def test_default_vat_codes_unchanged(db):
    def get(c):
        return db.execute(
            "SELECT default_vat_code FROM account WHERE code=?", (c,)
        ).fetchone()[0]

    assert get("4210") == "NL_21" and get("4400") == "GEEN" and get("8050") == "EXPORT"


def test_every_account_matches_default_contexts(db):
    for code, type_, sys_, p, s, b in db.execute(
        "SELECT code, type, is_system, selectable_purchase, selectable_sales, "
        "selectable_bank FROM account"
    ):
        assert default_contexts(type_, bool(sys_), code) == (bool(p), bool(s), bool(b))


def test_backfill_user_added_rows(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "0006_company_profile")
    conn = sqlite3.connect(test_settings.database_path)
    conn.execute(
        "INSERT INTO account (code, name, type, is_postable, is_active, is_system) "
        "VALUES ('4777', 'Eigen kosten', 'expense', 1, 1, 0)"
    )
    conn.execute("INSERT INTO vat_code (code, name, rate_bp) VALUES ('KOR', 'KOR', 0)")
    conn.commit()
    conn.close()
    command.upgrade(cfg, "head")
    conn = sqlite3.connect(test_settings.database_path)
    assert conn.execute(
        "SELECT selectable_purchase, selectable_sales, selectable_bank FROM account "
        "WHERE code='4777'"
    ).fetchone() == (1, 0, 1)
    assert conn.execute(
        "SELECT sales_rubriek, purchase_rubriek, is_system FROM vat_code WHERE code='KOR'"
    ).fetchone() == (None, None, 0)
    conn.close()


def test_downgrade_to_base(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0006_company_profile")
    conn = sqlite3.connect(test_settings.database_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(account)")}
    assert "selectable_purchase" not in cols
    cols = {r[1] for r in conn.execute("PRAGMA table_info(vat_code)")}
    assert not {"sales_rubriek", "purchase_rubriek", "is_system"} & cols
    conn.close()
    command.downgrade(cfg, "base")


def test_alembic_check(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.check(cfg)


def test_new_error_codes():
    from app.domain import errors

    for name in (
        "DUPLICATE_CODE",
        "INVALID_VAT_RATE",
        "INVALID_RUBRIEK",
        "VAT_CODE_IN_LOCKED_PERIOD",
        "VAT_CODE_IS_DEFAULT",
        "VAT_CODE_SYSTEM",
    ):
        assert getattr(errors, name) == name
