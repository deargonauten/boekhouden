"""DB-level tests for the core ledger schema: constraints, triggers, seed."""
import re
import sqlite3

import pytest
from alembic import command

from app.seed.rgs_accounts import SEED_ACCOUNTS
from tests.conftest import alembic_config


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def account_id(db, code):
    return one(db, "SELECT id FROM account WHERE code=?", code)


def journal_id(db, code):
    return one(db, "SELECT id FROM journal WHERE code=?", code)


def make_year(db, year=2025):
    db.execute(
        "INSERT INTO fiscal_year (year, start_date, end_date, status) "
        "VALUES (?, ?, ?, 'open')",
        (year, f"{year}-01-01", f"{year}-12-31"),
    )
    fy = one(db, "SELECT id FROM fiscal_year WHERE year=?", year)
    ends = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for n in range(1, 13):
        db.execute(
            "INSERT INTO period (fiscal_year_id, number, start_date, end_date, status) "
            "VALUES (?, ?, ?, ?, 'open')",
            (fy, n, f"{year}-{n:02d}-01", f"{year}-{n:02d}-{ends[n - 1]:02d}"),
        )
    db.commit()
    return fy


def period_id(db, fy, number):
    return one(db, "SELECT id FROM period WHERE fiscal_year_id=? AND number=?", fy, number)


def add_entry(db, fy, n=1, date="2025-01-15", number="MEM-2025-0001", kind="normal", rev=None):
    db.execute(
        "INSERT INTO journal_entry (journal_id, period_id, entry_number, booking_date, "
        "description, kind, reverses_entry_id) VALUES (?, ?, ?, ?, 'x', ?, ?)",
        (journal_id(db, "MEM"), period_id(db, fy, n), number, date, kind, rev),
    )
    return one(db, "SELECT id FROM journal_entry WHERE entry_number=?", number)


def add_line(db, entry_id, line_no=1, debit=100, credit=0, acc="1210"):
    db.execute(
        "INSERT INTO journal_line (entry_id, line_no, account_id, debit_cents, credit_cents) "
        "VALUES (?, ?, ?, ?, ?)",
        (entry_id, line_no, account_id(db, acc), debit, credit),
    )


def posted_entry(db):
    fy = make_year(db)
    e = add_entry(db, fy)
    add_line(db, e, 1, 100, 0)
    add_line(db, e, 2, 0, 100, "8000")
    db.commit()
    return fy, e


# --- seed ---------------------------------------------------------------

def test_seed_accounts_unique_and_valid(db):
    codes = [r[0] for r in db.execute("SELECT code FROM account")]
    assert len(codes) == len(set(codes)) == len(SEED_ACCOUNTS)
    assert all(re.fullmatch(r"\d{4}", c) for c in codes)


def test_seed_required_system_codes(db):
    for code in ["1300", "3000", "3100", "3110", "3120", "3130", "1400", "1410",
                 "3150", "2000", "2010", "2020", "8000"]:
        assert one(db, "SELECT is_system FROM account WHERE code=?", code) == 1


def test_seed_rgs_code_format(db):
    for (rgs,) in db.execute("SELECT rgs_code FROM account WHERE rgs_code IS NOT NULL"):
        assert re.fullmatch(r"[BW][A-Za-z]+", rgs)


def test_seed_default_vat_codes(db):
    assert one(db, "SELECT default_vat_code FROM account WHERE code='8000'") == "NL_21"
    assert one(db, "SELECT default_vat_code FROM account WHERE code='8050'") == "EXPORT"
    assert one(db, "SELECT default_vat_code FROM account WHERE code='4400'") == "GEEN"
    assert one(db, "SELECT default_vat_code FROM account WHERE code='4200'") == "NL_21"


def test_seed_vat_codes(db):
    rows = dict(db.execute("SELECT code, rate_bp FROM vat_code").fetchall())
    assert rows == {
        "GEEN": 0, "NL_21": 2100, "NL_9": 900, "NL_0": 0, "VERLEGD": 0,
        "EU_GOEDEREN": 0, "EU_DIENSTEN": 0, "EXPORT": 0,
    }


def test_seed_journals(db):
    rows = db.execute(
        "SELECT j.code, j.type, a.code, a.type FROM journal j "
        "LEFT JOIN account a ON a.id = j.account_id ORDER BY j.code"
    ).fetchall()
    assert {r[0] for r in rows} == {"VK", "IK", "BANK", "KAS", "MEM"}
    by_code = {r[0]: r for r in rows}
    assert by_code["BANK"][2:] == ("1210", "asset")
    assert by_code["KAS"][2:] == ("1100", "asset")


def test_seed_creates_no_fiscal_year(db):
    assert one(db, "SELECT count(*) FROM fiscal_year") == 0


# --- CHECK / unique constraints ----------------------------------------

@pytest.mark.parametrize("code", ["123", "12345", "12a4", "abcd"])
def test_account_code_check(db, code):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO account (code, name, type) VALUES (?, 'x', 'asset')", (code,))


def test_account_type_check_and_unique_code(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO account (code, name, type) VALUES ('9999', 'x', 'bogus')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO account (code, name, type) VALUES ('1300', 'x', 'asset')")


def test_journal_bank_requires_account_and_code_rules(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO journal (code, name, type) VALUES ('B2', 'x', 'bank')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO journal (code, name, type) VALUES ('lower', 'x', 'memoriaal')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO journal (code, name, type) VALUES ('TOOLONG7', 'x', 'memoriaal')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO journal (code, name, type) VALUES ('Z', 'x', 'bogus')")


def test_vat_fk_enforced_on_line(db):
    fy = make_year(db)
    e = add_entry(db, fy)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO journal_line (entry_id, line_no, account_id, debit_cents, "
            "credit_cents, vat_code) VALUES (?, 1, ?, 100, 0, 'NOPE')",
            (e, account_id(db, "1210")),
        )


@pytest.mark.parametrize("debit,credit", [(0, 0), (100, 100), (-5, 0), (0, -5)])
def test_line_amount_check(db, debit, credit):
    fy = make_year(db)
    e = add_entry(db, fy)
    with pytest.raises(sqlite3.IntegrityError):
        add_line(db, e, 1, debit, credit)


def test_line_no_unique_per_entry(db):
    fy = make_year(db)
    e = add_entry(db, fy)
    add_line(db, e, 1)
    with pytest.raises(sqlite3.IntegrityError):
        add_line(db, e, 1)


def test_entry_kind_and_storno_checks(db):
    fy = make_year(db)
    e = add_entry(db, fy)
    with pytest.raises(sqlite3.IntegrityError):
        add_entry(db, fy, number="MEM-2025-0002", kind="bogus")
    with pytest.raises(sqlite3.IntegrityError):  # storno without reverses
        add_entry(db, fy, number="MEM-2025-0003", kind="storno")
    with pytest.raises(sqlite3.IntegrityError):  # normal with reverses
        add_entry(db, fy, number="MEM-2025-0004", kind="normal", rev=e)


def test_entry_number_unique_and_single_storno(db):
    fy = make_year(db)
    e = add_entry(db, fy)
    with pytest.raises(sqlite3.IntegrityError):
        add_entry(db, fy)  # same entry_number
    add_entry(db, fy, number="MEM-2025-0002", kind="storno", rev=e)
    with pytest.raises(sqlite3.IntegrityError):
        add_entry(db, fy, number="MEM-2025-0003", kind="storno", rev=e)


def test_period_number_check_and_unique(db):
    fy = make_year(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO period (fiscal_year_id, number, start_date, end_date) "
            "VALUES (?, 13, '2025-12-01', '2025-12-31')", (fy,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO period (fiscal_year_id, number, start_date, end_date) "
            "VALUES (?, 1, '2025-01-01', '2025-01-31')", (fy,))


def test_duplicate_year_rejected(db):
    make_year(db)
    with pytest.raises(sqlite3.IntegrityError):
        make_year(db)


# --- immutability triggers ----------------------------------------------

def test_entry_and_line_update_delete_rejected(db):
    _, e = posted_entry(db)
    for sql in [
        "UPDATE journal_entry SET description='y'",
        "DELETE FROM journal_entry",
        "UPDATE journal_line SET debit_cents=1",
        "DELETE FROM journal_line",
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
            db.execute(sql)
    assert one(db, "SELECT count(*) FROM journal_line") == 2


def test_entry_sequence_is_updatable(db):
    fy = make_year(db)
    j = journal_id(db, "MEM")
    db.execute("INSERT INTO entry_sequence VALUES (?, ?, 1)", (j, fy))
    db.execute("UPDATE entry_sequence SET last_number=2")
    assert one(db, "SELECT last_number FROM entry_sequence") == 2


def test_insert_entry_into_locked_period_rejected(db):
    fy = make_year(db)
    db.execute("UPDATE period SET status='locked', locked_at=CURRENT_TIMESTAMP WHERE number=1")
    with pytest.raises(sqlite3.IntegrityError):
        add_entry(db, fy, n=1)
    add_entry(db, fy, n=2, date="2025-02-10")  # other period still open


def test_insert_entry_date_outside_period_rejected(db):
    fy = make_year(db)
    with pytest.raises(sqlite3.IntegrityError):
        add_entry(db, fy, n=1, date="2025-02-01")


def test_insert_line_into_locked_period_rejected(db):
    fy = make_year(db)
    e = add_entry(db, fy)
    db.execute("UPDATE period SET status='locked', locked_at=CURRENT_TIMESTAMP WHERE number=1")
    with pytest.raises(sqlite3.IntegrityError):
        add_line(db, e, 1)


# --- period / fiscal year lock triggers ----------------------------------

def test_period_open_to_locked_allowed_and_idempotent(db):
    make_year(db)
    db.execute("UPDATE period SET status='locked', locked_at='2025-03-01 10:00:00' WHERE number=1")
    # no-op identical update is allowed
    db.execute("UPDATE period SET status='locked', locked_at='2025-03-01 10:00:00' WHERE number=1")
    assert one(db, "SELECT status FROM period WHERE number=1") == "locked"


def test_period_unlock_and_other_changes_rejected(db):
    make_year(db)
    db.execute("UPDATE period SET status='locked', locked_at=CURRENT_TIMESTAMP WHERE number=1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE period SET status='open', locked_at=NULL WHERE number=1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE period SET end_date='2025-01-30' WHERE number=2")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE period SET number=5 WHERE number=2")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM period WHERE number=2")


def test_fiscal_year_close_only(db):
    make_year(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE fiscal_year SET year=2030")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM fiscal_year")
    db.execute("UPDATE fiscal_year SET status='closed'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE fiscal_year SET status='open'")


# --- migration lifecycle ---------------------------------------------------

def test_downgrade_removes_everything_and_reupgrade_works(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    conn = sqlite3.connect(test_settings.database_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert {n for n in names if not n.startswith("sqlite_autoindex")} <= {"alembic_version"}
    command.upgrade(cfg, "head")
    command.check(cfg)
