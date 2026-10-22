from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.ledger import validate_entry
from app.domain.sales.amounts import compute_totals
from app.domain.sales.entries import EntryLine, SalesAccounts, build_entry, format_number
from app.domain.sales.types import LineInput

RATES = {"NL_21": 2100, "NL_9": 900, "NL_0": 0}
ACC = SalesAccounts(debtors=1, vat_high=2, vat_low=3)


def build(lines, kind="invoice"):
    totals = compute_totals(lines, RATES)
    entry_lines = [
        EntryLine(account_id=l.account_id, vat_code=l.vat_code, line_excl_cents=a)
        for l, a in zip(lines, totals.line_excl_cents)
    ]
    return build_entry(
        kind=kind,
        number="2026-0001",
        invoice_date=date(2026, 3, 1),
        customer_name="Klant BV",
        lines=entry_lines,
        groups=totals.groups,
        total_incl_cents=totals.total_incl_cents,
        accounts=ACC,
        journal_id=9,
    ), totals


def L(price, code, account):
    return LineInput("x", 1000, price, code, account)


def test_invoice_entry_shape_and_balance():
    entry, totals = build([L(10000, "NL_21", 10), L(5000, "NL_9", 11), L(2500, "NL_0", 12)])
    validate_entry(entry)
    assert entry.journal_id == 9
    assert entry.reference == "2026-0001"
    assert entry.description == "Klant BV - 2026-0001"
    assert entry.booking_date == date(2026, 3, 1)
    debit = [l for l in entry.lines if l.debit_cents]
    assert [(l.account_id, l.debit_cents) for l in debit] == [(1, totals.total_incl_cents)]
    credit = {(l.account_id, l.vat_code): l.credit_cents for l in entry.lines if l.credit_cents}
    assert credit == {
        (10, "NL_21"): 10000,
        (11, "NL_9"): 5000,
        (12, "NL_0"): 2500,
        (2, None): 2100,  # BTW lines carry no vat code
        (3, None): 450,
    }


def test_credit_note_swaps_sides():
    entry, totals = build([L(10000, "NL_21", 10)], kind="credit_note")
    validate_entry(entry)
    assert [(l.account_id, l.credit_cents) for l in entry.lines if l.credit_cents] == [(1, 12100)]
    assert {(l.account_id, l.debit_cents) for l in entry.lines if l.debit_cents} == {(10, 10000), (2, 2100)}


def test_zero_amount_lines_are_skipped_and_zero_vat_group_has_no_line():
    entry, _ = build([L(0, "NL_21", 10), L(1000, "NL_0", 12)])
    validate_entry(entry)
    assert [l.account_id for l in entry.lines] == [1, 12]


def test_long_customer_name_is_truncated_to_255():
    totals = compute_totals([L(100, "NL_0", 12)], RATES)
    entry = build_entry(
        kind="invoice", number="2026-0001", invoice_date=date(2026, 3, 1), customer_name="K" * 400,
        lines=[EntryLine(12, "NL_0", 100)], groups=totals.groups, total_incl_cents=100,
        accounts=ACC, journal_id=1,
    )
    assert len(entry.description) == 255
    validate_entry(entry)


def test_all_zero_cannot_be_posted():
    entry, _ = build([L(0, "NL_21", 10)])
    with pytest.raises(LedgerError):
        validate_entry(entry)


def test_format_number():
    assert format_number(2026, 1) == "2026-0001"
    assert format_number(2026, 12345) == "2026-12345"
