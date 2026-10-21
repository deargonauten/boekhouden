import random
from datetime import date

import pytest
from sqlalchemy import select, text

from app.domain.errors import LedgerError
from app.domain.ledger import (
    NewEntry, NewLine, create_fiscal_year, get_entry, list_fiscal_years,
    lock_period, post_entry, set_account_active, set_journal_active,
)
from app.models import JournalLine


def entry(jrn, acc, day=date(2025, 3, 10), journal="MEM", **kw):
    default = [NewLine(acc("1210"), debit_cents=500), NewLine(acc("8000"), credit_cents=500)]
    return NewEntry(
        journal_id=jrn(journal),
        booking_date=day,
        description="Test",
        lines=kw.pop("lines", default),
        **kw,
    )


def test_post_and_read_back(session, year2025, jrn, acc):
    e = post_entry(session, entry(jrn, acc, reference="F-1"))
    session.commit()
    assert e.entry_number == "MEM-2025-0001"
    assert e.kind == "normal" and e.reference == "F-1"
    d = get_entry(session, e.id)
    assert [(l.debit_cents, l.credit_cents) for l in d.lines] == [(500, 0), (0, 500)]
    assert d.total_cents == 500
    assert d.lines[0].account_code == "1210"


def test_get_entry_unknown_returns_none(session):
    assert get_entry(session, 4242) is None


def test_numbering_sequential_per_journal_and_year(session, jrn, acc):
    create_fiscal_year(session, 2025)
    create_fiscal_year(session, 2026)
    nums = [post_entry(session, entry(jrn, acc)).entry_number for _ in range(3)]
    other = post_entry(session, entry(jrn, acc, journal="VK")).entry_number
    nextyear = post_entry(session, entry(jrn, acc, day=date(2026, 1, 5))).entry_number
    assert nums == ["MEM-2025-0001", "MEM-2025-0002", "MEM-2025-0003"]
    assert other == "VK-2025-0001"
    assert nextyear == "MEM-2026-0001"


def test_rejected_post_consumes_no_number(session, year2025, jrn, acc):
    post_entry(session, entry(jrn, acc))
    bad = entry(jrn, acc, lines=[NewLine(acc("1210"), debit_cents=500), NewLine(acc("8000"), credit_cents=499)])
    with pytest.raises(LedgerError) as ei:
        post_entry(session, bad)
    assert ei.value.code == "UNBALANCED"
    with pytest.raises(LedgerError):
        post_entry(session, entry(jrn, acc, day=date(2030, 1, 1)))  # no boekjaar
    assert post_entry(session, entry(jrn, acc)).entry_number == "MEM-2025-0002"


def test_db_failure_after_sequence_leaves_no_gap(session, year2025, jrn, acc, monkeypatch):
    """A DB-level failure mid-post rolls back the sequence bump too."""
    from app.domain.ledger import service

    post_entry(session, entry(jrn, acc))
    session.commit()
    real = service._insert_lines

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(service, "_insert_lines", boom)
    with pytest.raises(RuntimeError):
        post_entry(session, entry(jrn, acc))
    monkeypatch.setattr(service, "_insert_lines", real)
    assert post_entry(session, entry(jrn, acc)).entry_number == "MEM-2025-0002"
    session.commit()
    n = session.execute(text("SELECT COUNT(*) FROM journal_entry")).scalar()
    assert n == 2


def test_too_few_lines(session, year2025, jrn, acc):
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, lines=[NewLine(acc("1210"), debit_cents=5)]))
    assert ei.value.code == "TOO_FEW_LINES"


def test_account_checks(session, year2025, jrn, acc):
    set_account_active(session, acc("4200"), False)
    lines = [NewLine(acc("4200"), debit_cents=5), NewLine(acc("1210"), credit_cents=5)]
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, lines=lines))
    assert ei.value.code == "ACCOUNT_INACTIVE"
    lines = [NewLine(99999, debit_cents=5), NewLine(acc("1210"), credit_cents=5)]
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, lines=lines))
    assert ei.value.code == "ACCOUNT_NOT_FOUND"


def test_non_postable_account_rejected(session, year2025, jrn, acc):
    session.execute(text("UPDATE account SET is_postable=0 WHERE code='4200'"))
    lines = [NewLine(acc("4200"), debit_cents=5), NewLine(acc("1210"), credit_cents=5)]
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, lines=lines))
    assert ei.value.code == "ACCOUNT_NOT_POSTABLE"


def test_vat_code_validation(session, year2025, jrn, acc):
    lines = [NewLine(acc("1210"), debit_cents=121), NewLine(acc("8000"), credit_cents=121, vat_code="NOPE")]
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, lines=lines))
    assert ei.value.code == "INVALID_VAT_CODE"
    session.execute(text("UPDATE vat_code SET is_active=0 WHERE code='NL_9'"))
    lines = [NewLine(acc("1210"), debit_cents=121), NewLine(acc("8000"), credit_cents=121, vat_code="NL_9")]
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, lines=lines))
    assert ei.value.code == "INVALID_VAT_CODE"
    lines = [NewLine(acc("1210"), debit_cents=121), NewLine(acc("8000"), credit_cents=121, vat_code="NL_21")]
    e = post_entry(session, entry(jrn, acc, lines=lines))
    assert get_entry(session, e.id).lines[1].vat_code == "NL_21"


def test_no_year_and_locked_period(session, year2025, jrn, acc):
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc, day=date(2031, 1, 1)))
    assert ei.value.code == "NO_OPEN_PERIOD"
    assert "boekjaar" in ei.value.message.lower()
    march = [p for p in list_fiscal_years(session)[0].periods if p.number == 3][0]
    lock_period(session, march.id)
    with pytest.raises(LedgerError) as ei:
        post_entry(session, entry(jrn, acc))
    assert ei.value.code == "PERIOD_LOCKED"


def test_opening_only_in_memoriaal(session, year2025, jrn, acc):
    e = post_entry(session, entry(jrn, acc, kind="opening"))
    assert e.kind == "opening"
    with pytest.raises(LedgerError):
        post_entry(session, entry(jrn, acc, journal="VK", kind="opening"))


def test_storno_kind_not_allowed_directly(session, year2025, jrn, acc):
    with pytest.raises(LedgerError):
        post_entry(session, entry(jrn, acc, kind="storno"))


def test_inactive_journal_rejected(session, year2025, jrn, acc):
    set_journal_active(session, jrn("VK"), False)
    with pytest.raises(LedgerError):
        post_entry(session, entry(jrn, acc, journal="VK"))


def test_unknown_journal_rejected(session, year2025, acc):
    e = NewEntry(9999, date(2025, 3, 1), "x", [NewLine(acc("1210"), debit_cents=5), NewLine(acc("8000"), credit_cents=5)])
    with pytest.raises(LedgerError) as ei:
        post_entry(session, e)
    assert ei.value.code == "JOURNAL_NOT_FOUND"


def test_immutable_at_db_level(session, year2025, jrn, acc):
    post_entry(session, entry(jrn, acc))
    session.commit()
    for sql in [
        "UPDATE journal_entry SET description='x'",
        "DELETE FROM journal_entry",
        "UPDATE journal_line SET debit_cents=1",
        "DELETE FROM journal_line",
    ]:
        with pytest.raises(Exception):
            session.execute(text(sql))
        session.rollback()
    assert len(session.scalars(select(JournalLine)).all()) == 2


def test_ledger_always_balanced(session, year2025, jrn, acc):
    rnd = random.Random(1)
    accounts = [acc(c) for c in ("1210", "1300", "8000", "4200", "3100")]
    for _ in range(40):
        amount = rnd.randint(1, 100000)
        a, b = rnd.sample(accounts, 2)
        day = date(2025, rnd.randint(1, 12), rnd.randint(1, 28))
        lines = [NewLine(a, debit_cents=amount), NewLine(b, credit_cents=amount)]
        post_entry(session, entry(jrn, acc, day=day, lines=lines))
    d, c = session.execute(text("SELECT SUM(debit_cents), SUM(credit_cents) FROM journal_line")).one()
    assert d == c and d > 0
