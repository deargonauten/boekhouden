"""Indienen boekt de btw-rekeningen van de periode door naar 3150 (rekening-courant Belastingdienst)."""

from datetime import date

import pytest
from sqlalchemy import select

from app.domain.ledger import trial_balance
from app.domain.vat.filing import file_vat_return
from app.domain.vat.periods import VatPeriod
from app.models import JournalEntry
from tests.vat.vat_helpers import Book, set_company

TODAY = date(2026, 10, 23)
Q3 = VatPeriod(2026, "quarter", 3)


@pytest.fixture
def book(session):
    b = Book(session)
    set_company(session)
    return b


def bal(session, code):
    return {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session)}.get(code, 0)


def file(session, period=Q3):
    return file_vat_return(session, period, filed_on=date(2026, 10, 20), today=TODAY)


def test_amount_to_pay_moves_to_current_account(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    book.purchase(20000, 4200, day=date(2026, 8, 5))
    file(session)
    assert bal(session, "3100") == 0 and bal(session, "1400") == 0
    assert bal(session, "3150") == -16800  # schuld aan de Belastingdienst


def test_refund_moves_to_current_account_as_claim(session, book):
    book.purchase(100000, 21000, day=date(2026, 8, 5))
    file(session)
    assert bal(session, "1400") == 0 and bal(session, "3150") == 21000


def test_entry_is_dated_end_of_period_in_memoriaal_and_in_plain_dutch(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    file(session)
    e = session.scalars(select(JournalEntry).order_by(JournalEntry.id.desc())).first()
    assert e.booking_date == date(2026, 9, 30)
    assert "3e kwartaal 2026" in e.description


def test_only_movements_inside_the_period_are_settled(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    book.sale(50000, 10500, day=date(2026, 10, 3))  # Q4
    file(session)
    assert bal(session, "3100") == -10500 and bal(session, "3150") == -21000


def test_nihilaangifte_posts_nothing(session, book):
    before = session.scalar(select(JournalEntry.id).order_by(JournalEntry.id.desc()))
    file(session)
    assert session.scalar(select(JournalEntry.id).order_by(JournalEntry.id.desc())) == before


def test_paying_the_aangifte_clears_the_current_account(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    file(session)
    book.post([("3150", 21000, 0), ("1210", 0, 21000)], day=date(2026, 10, 25), journal="BANK")
    assert bal(session, "3150") == 0


def test_settlement_does_not_change_the_return(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    f = file(session)
    assert f.total_cents == 21000
