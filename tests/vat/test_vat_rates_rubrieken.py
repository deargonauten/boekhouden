import pytest

from app.domain.errors import LedgerError
from app.domain.vat.rates import parse_rate_bp
from app.domain.vat.rubrieken import (
    ALSO_INPUT_VAT, PURCHASE_RUBRIEKEN, SALES_RUBRIEKEN, suggest_rubrieken,
)

RATE_MSG = "Vul een percentage tussen 0 en 99,99 in, bijvoorbeeld 21 of 6,5."


@pytest.mark.parametrize("text,bp", [
    ("21", 2100), ("21,0", 2100), ("6,5", 650), ("6.5", 650), ("0", 0),
    (" 9 ", 900), ("99,99", 9999), ("0,01", 1), ("21%", 2100),
])
def test_parse_ok(text, bp):
    assert parse_rate_bp(text) == bp


@pytest.mark.parametrize("text", [
    "21,999", "-1", "abc", "1e2", "", "  ", "100", "99,991", "100,00", "1,2,3", ",5", "NaN", "Infinity",
])
def test_parse_rejected(text):
    with pytest.raises(LedgerError) as ei:
        parse_rate_bp(text)
    assert ei.value.code == "INVALID_VAT_RATE"
    assert ei.value.message == RATE_MSG


def test_catalogue():
    assert set(SALES_RUBRIEKEN) == {"1a", "1b", "1c", "1d", "1e", "3a", "3b", "3c"}
    assert set(PURCHASE_RUBRIEKEN) == {"2a", "4a", "4b", "5b"}
    assert SALES_RUBRIEKEN["1a"] == "Omzet met 21% btw"
    assert PURCHASE_RUBRIEKEN["5b"] == "Voorbelasting (btw die je terugkrijgt)"
    assert ALSO_INPUT_VAT == {"2a", "4a", "4b"}


@pytest.mark.parametrize("rate,expected", [
    (2100, ("1a", "5b")), (900, ("1b", "5b")), (0, ("1e", None)),
    (650, ("1c", "5b")), (1900, ("1c", "5b")),
])
def test_suggest_rubrieken(rate, expected):
    assert suggest_rubrieken(rate) == expected
