"""Buitenlandse facturen: vreemde valuta en verlegde btw (pure booking rules)."""

import pytest

from app.domain.ledger import validate_entry
from app.domain.purchase.booking import AccountIds, build_entry, check_bookable, preview_lines
from app.domain.purchase.errors import INVALID_TOTALS, MISSING_FIELD, UNSUPPORTED_VAT, BookingError
from tests.purchase.test_booking import COSTS, RUBRIEKEN, inp, line, side

ACC = AccountIds(creditors=300, vat_receivable=140, vat_shifted_receivable=141, vat_shifted_payable=313)
RATE = 1_250_000  # 1 EUR = 1,25 USD


def raises(data, code, field=None):
    with pytest.raises(BookingError) as exc:
        check_bookable(data)
    assert exc.value.code == code
    if field:
        assert exc.value.field == field
    return exc.value


# --- reverse charge, euro -------------------------------------------------------------
@pytest.mark.parametrize("code", ["EU_DIENSTEN", "EU_GOEDEREN", "EXPORT", "VERLEGD"])
def test_reverse_charge_books_vat_both_ways(code):
    data = inp(line(10000, 0, code), shifted_vat_rate_bp=2100)
    check_bookable(data)
    entry = build_entry(data, ACC, journal_id=5)
    validate_entry(entry)
    assert side(entry, COSTS) == (10000, 0)
    assert side(entry, 141) == (2100, 0)  # voorbelasting verlegd
    assert side(entry, 313) == (0, 2100)  # af te dragen verlegd
    assert side(entry, 300) == (0, 10000)  # supplier is paid the net amount only
    assert side(entry, 140) == (0, 0)
    assert [l.vat_code for l in entry.lines if l.account_id == COSTS] == [code]
    assert all(l.vat_code is None for l in entry.lines if l.account_id in (141, 313))


def test_reverse_charge_rate_nine_percent_and_zero():
    entry = build_entry(inp(line(10000, 0, "EU_DIENSTEN"), shifted_vat_rate_bp=900), ACC, 5)
    assert side(entry, 313) == (0, 900)
    entry = build_entry(inp(line(10000, 0, "EU_DIENSTEN"), shifted_vat_rate_bp=0), ACC, 5)
    assert side(entry, 313) == (0, 0) and side(entry, 141) == (0, 0)


def test_reverse_charge_mixed_with_dutch_vat_line():
    data = inp(line(10000, 0, "EU_DIENSTEN"), line(5000, 1050, "NL_21"))
    entry = build_entry(data, ACC, 5)
    validate_entry(entry)
    assert side(entry, 140) == (1050, 0)
    assert side(entry, 313) == (0, 2100)
    assert side(entry, 300) == (0, 16050)


def test_reverse_charge_credit_note_swaps_sides():
    entry = build_entry(inp(line(10000, 0, "EU_DIENSTEN"), kind="credit_note"), ACC, 5)
    validate_entry(entry)
    assert side(entry, 141) == (0, 2100)
    assert side(entry, 313) == (2100, 0)
    assert side(entry, 300) == (10000, 0)


def test_reverse_charge_line_with_printed_vat_is_refused():
    err = raises(inp(line(10000, 2100, "EU_DIENSTEN")), UNSUPPORTED_VAT, "line.0.vat_amount")
    assert "verlegd" in err.message.lower() and "0,00" in err.message


def test_reverse_charge_needs_system_accounts():
    data = inp(line(10000, 0, "EU_DIENSTEN"))
    with pytest.raises(BookingError):
        build_entry(data, AccountIds(creditors=300, vat_receivable=140), 5)


def test_unknown_rubriek_still_refused():
    data = inp(line(10000, 0, "MIJN_X"), vat_purchase_rubrieken={**RUBRIEKEN, "MIJN_X": "3b"})
    raises(data, UNSUPPORTED_VAT, "line.0.vat_code")


# --- foreign currency -----------------------------------------------------------------
def test_foreign_currency_needs_exchange_rate():
    err = raises(inp(currency="USD"), MISSING_FIELD, "exchange_rate")
    assert "wisselkoers" in err.message.lower() and "USD" in err.message


def test_foreign_amounts_are_converted_per_line():
    # 100,00 USD / 1,25 = 80,00 EUR. Printed Dutch BTW is converted too.
    data = inp(line(10000, 2100), currency="USD", exchange_rate_micro=RATE)
    check_bookable(data)
    entry = build_entry(data, ACC, 5)
    validate_entry(entry)
    assert side(entry, COSTS) == (8000, 0)
    assert side(entry, 140) == (1680, 0)
    assert side(entry, 300) == (0, 9680)


def test_foreign_currency_totals_are_checked_in_foreign_currency():
    err = raises(inp(line(10000, 2100), currency="USD", exchange_rate_micro=RATE, total_incl_cents=999),
                 INVALID_TOTALS, "total_incl")
    assert "USD" in err.message


def test_foreign_rounding_always_balances():
    lines = (line(333, 0, "EU_DIENSTEN"), line(333, 0, "EU_DIENSTEN"), line(334, 0, "EU_DIENSTEN"))
    data = inp(*lines, currency="USD", exchange_rate_micro=3_000_000)
    validate_entry(build_entry(data, ACC, 5))


def test_foreign_reverse_charge_vat_is_over_euro_amount():
    data = inp(line(10000, 0, "EU_DIENSTEN"), currency="USD", exchange_rate_micro=RATE)
    entry = build_entry(data, ACC, 5)
    assert side(entry, 313) == (0, 1680)  # 21% of 80,00
    assert side(entry, 300) == (0, 8000)


def test_euro_invoice_ignores_exchange_rate():
    data = inp(line(), exchange_rate_micro=RATE)
    assert side(build_entry(data, ACC, 5), COSTS) == (10000, 0)


def test_preview_mentions_currency_and_reverse_charge():
    data = inp(line(10000, 0, "EU_DIENSTEN"), currency="USD", exchange_rate_micro=RATE)
    table = preview_lines(data, ACC, {COSTS: ("4200", "Kosten"), 141: ("1410", "x"), 313: ("3130", "y"),
                                     300: ("3000", "Crediteuren")}, {"EU_DIENSTEN": "0%"})
    assert "USD" in table.summary and "80,00" in table.summary
    labels = [r.label for r in table.rows]
    assert "BTW die je terugkrijgt (verlegd)" in labels
    assert "BTW die je afdraagt (verlegd)" in labels
    assert table.total_to_pay_cents == 8000
