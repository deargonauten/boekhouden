from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import create_db_engine
from app.domain.ledger import NewEntry, NewLine, create_fiscal_year, post_entry
from app.models import Account, Journal
from tests.conftest import migrate_to_head


@pytest.fixture
def engine(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    migrate_to_head(test_settings)
    engine = create_db_engine(test_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def acc(session):
    """Look up an account id by its 4-digit code."""

    def _acc(code: str) -> int:
        return session.scalar(select(Account.id).where(Account.code == code))

    return _acc


@pytest.fixture
def jrn(session):
    """Look up a journal id by its code."""

    def _jrn(code: str) -> int:
        return session.scalar(select(Journal.id).where(Journal.code == code))

    return _jrn


@pytest.fixture
def year2025(session):
    fy = create_fiscal_year(session, 2025)
    session.commit()
    return fy


@pytest.fixture
def make_entry(session, acc, jrn):
    """Post and commit a simple balanced bank/revenue entry."""

    def _make(journal="MEM", day=date(2025, 3, 10), cents=1000, **kw):
        entry = NewEntry(
            journal_id=jrn(journal),
            booking_date=day,
            description=kw.pop("description", "Test"),
            lines=[
                NewLine(acc("1210"), debit_cents=cents),
                NewLine(acc("8400"), credit_cents=cents),
            ],
            **kw,
        )
        e = post_entry(session, entry)
        session.commit()
        return e

    return _make
