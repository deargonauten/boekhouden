from datetime import date

import pytest
from sqlalchemy import text

from app.domain.errors import LedgerError
from app.domain.ledger import (
    close_fiscal_year, create_fiscal_year, list_fiscal_years, lock_period,
)


def test_create_fiscal_year(session):
    fy = create_fiscal_year(session, 2024)
    session.commit()
    assert (fy.year, fy.start_date, fy.end_date, fy.status) == (2024, date(2024, 1, 1), date(2024, 12, 31), "open")
    ys = list_fiscal_years(session)
    assert len(ys[0].periods) == 12
    assert [p.number for p in ys[0].periods] == list(range(1, 13))
    assert ys[0].periods[1].end_date == date(2024, 2, 29)
    assert all(p.status == "open" for p in ys[0].periods)


def test_duplicate_year(session):
    create_fiscal_year(session, 2025)
    with pytest.raises(LedgerError) as ei:
        create_fiscal_year(session, 2025)
    assert ei.value.code == "YEAR_EXISTS"


def test_non_consecutive_years_ok(session):
    create_fiscal_year(session, 2020)
    create_fiscal_year(session, 2025)
    assert [y.year for y in list_fiscal_years(session)] == [2025, 2020]  # newest first


def test_lock_period_idempotent(session, year2025):
    p = list_fiscal_years(session)[0].periods[0]
    lock_period(session, p.id)
    first = list_fiscal_years(session)[0].periods[0].locked_at
    assert first is not None
    lock_period(session, p.id)
    again = list_fiscal_years(session)[0].periods[0]
    assert again.status == "locked" and again.locked_at == first


def test_lock_unknown_period(session):
    with pytest.raises(LedgerError) as ei:
        lock_period(session, 999)
    assert ei.value.code == "PERIOD_NOT_FOUND"


def test_locking_all_periods_closes_year(session, year2025):
    for p in list_fiscal_years(session)[0].periods[:11]:
        lock_period(session, p.id)
    assert list_fiscal_years(session)[0].status == "open"
    lock_period(session, list_fiscal_years(session)[0].periods[11].id)
    assert list_fiscal_years(session)[0].status == "closed"


def test_close_fiscal_year(session, year2025):
    lock_period(session, list_fiscal_years(session)[0].periods[4].id)
    close_fiscal_year(session, 2025)
    y = list_fiscal_years(session)[0]
    assert y.status == "closed" and all(p.status == "locked" for p in y.periods)
    close_fiscal_year(session, 2025)  # idempotent


def test_close_unknown_year(session):
    with pytest.raises(LedgerError) as ei:
        close_fiscal_year(session, 1999)
    assert ei.value.code == "YEAR_NOT_FOUND"


def test_no_unlock_at_db_level(session, year2025):
    p = list_fiscal_years(session)[0].periods[0]
    lock_period(session, p.id)
    session.commit()
    for sql in [
        f"UPDATE period SET status='open' WHERE id={p.id}",
        "UPDATE fiscal_year SET status='open'",
        f"DELETE FROM period WHERE id={p.id}",
    ]:
        with pytest.raises(Exception):
            session.execute(text(sql))
        session.rollback()


def test_db_trigger_refuses_entry_in_locked_period(session, year2025, jrn):
    """Even bypassing the service, the DB refuses entries in a locked period."""
    p = list_fiscal_years(session)[0].periods[2]
    lock_period(session, p.id)
    session.commit()
    with pytest.raises(Exception):
        session.execute(text(
            "INSERT INTO journal_entry(journal_id, period_id, entry_number, booking_date, description, kind) "
            f"VALUES ({jrn('MEM')}, {p.id}, 'X-1', '2025-03-10', 'x', 'normal')"))
