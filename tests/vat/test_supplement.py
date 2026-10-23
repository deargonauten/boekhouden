"""Suppletie: verschil tussen een ingediende aangifte en de stand per vandaag, meenemen in een latere aangifte."""

from datetime import date

import pytest
from sqlalchemy import text

from app.domain.ledger import trial_balance
from app.domain.vat.filing import file_vat_return, get_snapshot
from app.domain.vat.periods import VatPeriod
from app.domain.vat.supplement import (
    available_supplements, compare_with_filed, create_supplement, delete_supplement, get_supplement, pick_supplements,
)
from tests.vat.test_filing_lock import fails
from tests.vat.vat_helpers import Book, set_company

TODAY = date(2026, 10, 23)
Q2, Q3, Q4 = (VatPeriod(2026, "quarter", n) for n in (2, 3, 4))


@pytest.fixture
def book(session):
    b = Book(session)
    set_company(session)
    return b


def file(session, period, **kw):
    return file_vat_return(session, period, filed_on=date(2026, 10, 20), today=TODAY, **kw)


def late_purchase(session, book, net=10000, vat=2100, day=date(2026, 8, 20)):
    """A booking in the already locked Q3, only possible with explicit consent."""
    from app.domain.ledger import NewEntry, NewLine, post_entry
    from app.models import Journal
    from sqlalchemy import select
    jid = session.scalar(select(Journal.id).where(Journal.code == "IK"))
    lines = [NewLine(book.acc("4000"), debit_cents=net, vat_code="NL_21"),
             NewLine(book.acc("1400"), debit_cents=vat), NewLine(book.acc("2000"), credit_cents=net + vat)]
    entry = post_entry(session, NewEntry(jid, day, "Late inkoop", lines), allow_locked_period=True)
    session.flush()
    return entry


def bal(session, code):
    return {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session)}.get(code, 0)


@pytest.fixture
def filed_q3(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    file(session, Q3)
    return book


def test_no_difference_right_after_filing(session, filed_q3):
    c = compare_with_filed(session, Q3)
    assert not c.differs and c.diff_cents == 0 and c.filed_cents == 21000 == c.live_cents


def test_late_booking_shows_difference(session, filed_q3):
    late_purchase(session, filed_q3)
    c = compare_with_filed(session, Q3)
    assert c.differs
    assert (c.filed_cents, c.live_cents, c.diff_cents) == (21000, 18900, -2100)
    assert (c.filed_5b_cents, c.live_5b_cents) == (0, 2100)


def test_create_supplement_freezes_difference(session, filed_q3):
    late_purchase(session, filed_q3)
    s = create_supplement(session, Q3)
    assert s.total_cents == -2100 and s.included_in is None and s.period == Q3
    assert get_supplement(session, s.id).total_cents == -2100


def test_create_requires_filed_difference_and_single_open(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    assert fails("VAT_NOT_FILED", create_supplement, session, Q3)
    file(session, Q3)
    assert fails("VAT_NO_DIFFERENCE", create_supplement, session, Q3)
    late_purchase(session, book)
    create_supplement(session, Q3)
    assert fails("VAT_SUPPLEMENT_EXISTS", create_supplement, session, Q3)


def test_delete_until_included(session, filed_q3):
    late_purchase(session, filed_q3)
    s = create_supplement(session, Q3)
    delete_supplement(session, s.id)
    assert get_supplement(session, s.id) is None
    assert fails("VAT_SUPPLEMENT_NOT_FOUND", delete_supplement, session, s.id)


def test_include_in_later_return(session, filed_q3):
    late_purchase(session, filed_q3)
    s = create_supplement(session, Q3)
    filed_q3.sale(50000, 10500, day=date(2026, 11, 3))
    assert [x.id for x in available_supplements(session, Q4)] == [s.id]
    snap = get_snapshot(session, Q4, supplement_ids=[s.id])
    assert snap.totals["5g"] == 10500 - 2100 and [x.id for x in snap.supplements] == [s.id]
    filed = file_vat_return(session, Q4, filed_on=date(2026, 12, 5), today=date(2026, 12, 6), supplement_ids=[s.id])
    assert filed.total_cents == 8400
    assert get_supplement(session, s.id).included_in == Q4
    assert available_supplements(session, VatPeriod(2027, "quarter", 1)) == []
    assert fails("VAT_SUPPLEMENT_INCLUDED", delete_supplement, session, s.id)
    # q3 now matches again, and the leftover btw is settled on 3150 together with q4
    assert not compare_with_filed(session, Q3).differs
    assert not compare_with_filed(session, Q4).differs  # what Q4 took along is not Q4's own books
    assert bal(session, "1400") == 0 and bal(session, "3100") == 0
    assert bal(session, "3150") == -(21000 + 10500 - 2100)


def test_supplement_of_same_or_later_period_is_refused(session, filed_q3):
    late_purchase(session, filed_q3)
    s = create_supplement(session, Q3)
    assert available_supplements(session, Q3) == []
    assert fails("VAT_SUPPLEMENT_INVALID", pick_supplements, session, Q3, [s.id])
    assert fails("VAT_SUPPLEMENT_INVALID", get_snapshot, session, Q4, supplement_ids=[s.id + 99])


def test_second_supplement_after_first_was_included(session, filed_q3):
    late_purchase(session, filed_q3)
    s = create_supplement(session, Q3)
    file_vat_return(session, Q4, filed_on=date(2026, 12, 5), today=date(2026, 12, 6), supplement_ids=[s.id])
    late_purchase(session, filed_q3, net=20000, vat=4200, day=date(2026, 9, 1))
    c = compare_with_filed(session, Q3)
    assert c.diff_cents == -4200
    s2 = create_supplement(session, Q3)
    assert s2.total_cents == -4200


def test_database_refuses_changing_included_supplement(session, filed_q3):
    from sqlalchemy.exc import DatabaseError
    late_purchase(session, filed_q3)
    s = create_supplement(session, Q3)
    file_vat_return(session, Q4, filed_on=date(2026, 12, 5), today=date(2026, 12, 6), supplement_ids=[s.id])
    with pytest.raises(DatabaseError):
        session.execute(text("DELETE FROM vat_supplement"))
