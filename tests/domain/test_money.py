from decimal import Decimal

import pytest

from app.domain.errors import LedgerError
from app.domain.money import format_euro, parse_euro, require_cents


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1.234,56", 123456),
        ("12", 1200),
        ("12,5", 1250),
        ("-3,00", -300),
        ("€ 1,00", 100),
        ("€1,00", 100),
        ("0,01", 1),
        ("  7,05 ", 705),
        ("1.234.567,89", 123456789),
        ("1.234", 123400),
    ],
)
def test_parse_euro_valid(text, expected):
    assert parse_euro(text) == expected


@pytest.mark.parametrize("text", ["", "  ", "abc", "1,234", "12.5", "1,2,3", "1.23", "--1", "1,", ",5", "€"])
def test_parse_euro_rejects(text):
    with pytest.raises(ValueError) as exc:
        parse_euro(text)
    assert isinstance(exc.value, LedgerError)
    assert exc.value.code == "INVALID_AMOUNT"
    assert exc.value.message


def test_parse_euro_rejects_non_str():
    with pytest.raises(TypeError):
        parse_euro(12)


@pytest.mark.parametrize(
    "cents,expected",
    [
        (123456, "€ 1.234,56"),
        (0, "€ 0,00"),
        (5, "€ 0,05"),
        (100, "€ 1,00"),
        (-100, "-€ 1,00"),
        (-123456, "-€ 1.234,56"),
        (100000000, "€ 1.000.000,00"),
    ],
)
def test_format_euro(cents, expected):
    assert format_euro(cents) == expected


@pytest.mark.parametrize("cents", [0, 1, 99, 123456, -5, -123456])
def test_round_trip(cents):
    assert parse_euro(format_euro(cents).replace("-€", "-")) == cents


@pytest.mark.parametrize("bad", [1.5, 1.0, True, False, Decimal("1"), "1", None])
def test_require_cents_rejects(bad):
    with pytest.raises(TypeError):
        require_cents(bad)


def test_require_cents_accepts_int():
    assert require_cents(42) == 42
    assert require_cents(-42) == -42


def test_format_euro_rejects_float():
    with pytest.raises(TypeError):
        format_euro(1.5)
