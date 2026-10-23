from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.ledger import (
    NewEntry, NewLine, create_fiscal_year, get_entry, list_entries,
    list_fiscal_years, lock_period, post_entry, reverse_entry,
)


def test_storno_happy_path(session, year2025, make_entry):
    orig = make_entry(cents=1234)
    st = reverse_entry(session, orig.id)
    session.commit()
    assert st.kind == "storno" and st.reverses_entry_id == orig.id
    assert st.description == f"Storno {orig.entry_number}"
    assert st.booking_date == orig.booking_date
    assert st.journal_id == orig.journal_id
    d = get_entry(session, st.id)
    assert [(l.debit_cents, l.credit_cents) for l in d.lines] == [(0, 1234), (1234, 0)]
    o = get_entry(session, orig.id)
    assert o.reversed_by is not None and o.reversed_by.id == st.id
    assert not o.is_reversible and not d.is_reversible
    assert d.original is not None and d.original.id == orig.id


def test_reversible_flag_on_plain_entry(session, year2025, make_entry):
    assert get_entry(session, make_entry().id).is_reversible


def test_double_storno(session, year2025, make_entry):
    orig = make_entry()
    reverse_entry(session, orig.id)
    with pytest.raises(LedgerError) as ei:
        reverse_entry(session, orig.id)
    assert ei.value.code == "ALREADY_REVERSED"


def test_storno_of_storno(session, year2025, make_entry):
    st = reverse_entry(session, make_entry().id)
    with pytest.raises(LedgerError) as ei:
        reverse_entry(session, st.id)
    assert ei.value.code == "CANNOT_REVERSE_STORNO"


def test_storno_copies_vat_and_line_description(session, year2025, jrn, acc):
    e = post_entry(session, NewEntry(jrn("MEM"), date(2025, 3, 1), "x", [
        NewLine(acc("1210"), debit_cents=121, description="a"),
        NewLine(acc("8400"), credit_cents=121, description="b", vat_code="NL_21"),
    ]))
    d = get_entry(session, reverse_entry(session, e.id).id)
    assert d.lines[1].vat_code == "NL_21" and d.lines[1].description == "b"
    assert d.lines[0].account_code == "1210"


def test_storno_locked_period_defaults_to_today(session, year2025, make_entry, monkeypatch):
    from app.domain.ledger import service

    orig = make_entry(day=date(2025, 3, 10))
    create_fiscal_year(session, 2026)
    monkeypatch.setattr(service, "_today", lambda: date(2026, 2, 2))
    march = [y for y in list_fiscal_years(session) if y.year == 2025][0].periods[2]
    lock_period(session, march.id)
    st = reverse_entry(session, orig.id)
    assert st.booking_date == date(2026, 2, 2)
    assert st.period_id != orig.period_id
    assert st.entry_number == "MEM-2026-0001"


def test_storno_explicit_date_in_locked_period_fails(session, year2025, make_entry):
    orig = make_entry(day=date(2025, 3, 10))
    lock_period(session, list_fiscal_years(session)[0].periods[2].id)
    with pytest.raises(LedgerError) as ei:
        reverse_entry(session, orig.id, booking_date=date(2025, 3, 11))
    assert ei.value.code == "PERIOD_LOCKED"


def test_storno_explicit_date_and_description(session, year2025, make_entry):
    orig = make_entry(day=date(2025, 3, 10))
    st = reverse_entry(session, orig.id, booking_date=date(2025, 4, 1), description="Fout")
    assert st.booking_date == date(2025, 4, 1) and st.description == "Fout"


def test_storno_unknown_entry(session, year2025):
    with pytest.raises(LedgerError) as ei:
        reverse_entry(session, 12345)
    assert ei.value.code == "ENTRY_NOT_FOUND"


def test_list_entries_labels_and_paging(session, year2025, make_entry):
    a = make_entry()
    st = reverse_entry(session, a.id)
    for _ in range(3):
        make_entry(journal="VK")
    page = list_entries(session)
    assert page.total == 5
    by_id = {r.id: r for r in page.items}
    assert by_id[a.id].reversed_by_id == st.id and by_id[a.id].reversed_by_number == st.entry_number
    assert by_id[st.id].reverses_entry_id == a.id and by_id[st.id].reverses_number == a.entry_number
    assert by_id[a.id].total_cents == 1000
    assert by_id[a.id].journal_code == "MEM"
    assert page.items[0].id > page.items[-1].id  # newest first
    assert list_entries(session, journal_code="VK").total == 3
    small = list_entries(session, page=2, per_page=2)
    assert len(small.items) == 2 and small.pages == 3
