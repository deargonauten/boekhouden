import pytest

from app.domain.bank.amounts import parse_amount
from app.domain.bank.iban import bank_from_iban, find_iban, is_valid_iban, normalize_iban
from app.domain.bank.types import PARSE_ERROR, BankImportError


def test_normalize_iban():
    assert normalize_iban(" nl91 abna 0417 1643 00 ") == "NL91ABNA0417164300"
    assert normalize_iban(None) == ""


@pytest.mark.parametrize(
    "iban",
    ["NL91ABNA0417164300", "nl91 abna 0417 1643 00", "DE89370400440532013000", "BE68539007547034"],
)
def test_valid_ibans(iban):
    assert is_valid_iban(iban)


@pytest.mark.parametrize(
    "iban",
    ["", None, "NL91ABNA0417164301", "NL91ABNA04171643", "XX00", "1234567890", "NL91ABNA0417164300X"],
)
def test_invalid_ibans(iban):
    assert not is_valid_iban(iban)


def test_bank_from_iban():
    assert bank_from_iban("NL91ABNA0417164300") == "abn_amro"
    assert bank_from_iban("NL02INGB0001234567") == "ing"
    assert bank_from_iban("DE89370400440532013000") is None


def test_find_iban_in_text():
    assert find_iban("Betaling aan NL91 ABNA 0417 1643 00 voor factuur") == "NL91ABNA0417164300"
    assert find_iban("/IBAN/NL91ABNA0417164300/BIC/ABNANL2A/") == "NL91ABNA0417164300"
    assert find_iban("geen iban hier") is None


@pytest.mark.parametrize(
    "text,style,cents",
    [
        ("1.234,56", "nl", 123456),
        ("12,5", "nl", 1250),
        ("12", "nl", 1200),
        ("-1.000,00", "nl", -100000),
        ("+3,05", "nl", 305),
        ("0,07", "nl", 7),
        ("1234.56", "en", 123456),
        ("1,234.56", "en", 123456),
        ("-12.5", "en", -1250),
        ("1234,56", "mt940", 123456),
        ("100,", "mt940", 10000),
        ("0,01", "mt940", 1),
        (" € 9,99 ", "nl", 999),
    ],
)
def test_parse_amount(text, style, cents):
    result = parse_amount(text, style)
    assert result == cents and type(result) is int


@pytest.mark.parametrize(
    "text,style",
    [("1,234", "nl"), ("12,345", "nl"), ("12.345", "en"), ("abc", "nl"), ("", "nl"), ("-", "nl"), ("1,2,3", "nl")],
)
def test_parse_amount_rejects(text, style):
    with pytest.raises(BankImportError) as exc:
        parse_amount(text, style)
    assert exc.value.code == PARSE_ERROR
    assert "geen geldig bedrag" in exc.value.message


def test_parse_amount_more_than_two_decimals_mentions_it():
    with pytest.raises(BankImportError) as exc:
        parse_amount("1,005", "nl")
    assert "twee cijfers achter de komma" in exc.value.message
