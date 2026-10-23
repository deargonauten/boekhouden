"""Wisselkoersen: integer-only conversion of foreign amounts to euro cents."""

import pytest

from app.domain.errors import LedgerError
from app.domain.fx import format_amount, normalize_currency, parse_rate, to_eur_cents


def test_parse_rate_accepts_comma_and_dot():
    assert parse_rate("1,0842") == 1_084_200
    assert parse_rate("1.0842") == 1_084_200
    assert parse_rate(" 0,85 ") == 850_000
    assert parse_rate("151,3") == 151_300_000


@pytest.mark.parametrize("bad", ["", "abc", "0", "0,0", "-1,2", "1,2,3", "1,1234567"])
def test_parse_rate_rejects_nonsense_in_plain_dutch(bad):
    with pytest.raises(LedgerError) as exc:
        parse_rate(bad)
    assert "wisselkoers" in exc.value.message.lower()


def test_to_eur_cents_divides_by_rate_rounding_half_away_from_zero():
    # 100,00 USD at 1,25 USD per EUR = 80,00 EUR
    assert to_eur_cents(10_000, 1_250_000) == 8_000
    # 10,00 / 3 = 3,333.. -> 3,33
    assert to_eur_cents(1_000, 3_000_000) == 333
    # 0,05 / 3 -> 0,0166 -> 0,02
    assert to_eur_cents(5, 3_000_000) == 2
    assert to_eur_cents(-5, 3_000_000) == -2
    assert to_eur_cents(0, 1_084_200) == 0


def test_to_eur_cents_eur_rate_is_identity():
    assert to_eur_cents(12_345, 1_000_000) == 12_345


def test_normalize_currency():
    assert normalize_currency(" usd ") == "USD"
    assert normalize_currency("") == "EUR"
    assert normalize_currency(None) == "EUR"
    with pytest.raises(LedgerError):
        normalize_currency("US")
    with pytest.raises(LedgerError):
        normalize_currency("E1R")


def test_format_amount():
    assert format_amount(123_456, "USD") == "USD 1.234,56"
    assert format_amount(-100, "GBP") == "-GBP 1,00"
    assert format_amount(100, "EUR") == "€ 1,00"
