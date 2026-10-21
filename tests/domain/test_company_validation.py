import pytest

from app.domain.company.validation import (
    CompanyInput,
    format_iban,
    is_valid_btw_id,
    normalize_btw_id,
    validate_btw_id,
    validate_company_input,
    validate_nl_postal_code,
)
from app.domain.errors import CompanyError


def ok(**kw):
    kw.setdefault("legal_name", "Jansen")
    return validate_company_input(CompanyInput(**kw))


# --- kvk ---
@pytest.mark.parametrize("raw", ["12345678", "1234 5678", "1234.56-78"])
def test_kvk_ok(raw):
    assert ok(kvk=raw).kvk == "12345678"


@pytest.mark.parametrize("raw", ["1234567", "123456789", "1234567a"])
def test_kvk_bad(raw):
    with pytest.raises(CompanyError) as e:
        ok(kvk=raw)
    assert e.value.messages == [
        "Je KvK-nummer bestaat uit 8 cijfers, bijvoorbeeld 12345678. Controleer het nummer."
    ]
    assert e.value.codes == ["INVALID_COMPANY_KVK"]


def test_kvk_empty_none():
    assert ok(kvk="  ").kvk is None
    assert ok().kvk is None


# --- btw id ---
@pytest.mark.parametrize("raw", ["NL123456789B01", "nl 1234.56789-b01"])
def test_btw_ok(raw):
    assert ok(btw_id=raw).btw_id == "NL123456789B01"
    assert validate_btw_id(raw) == "NL123456789B01"


@pytest.mark.parametrize("raw", ["DE123456789", "NL12345678B01", "NL123456789B1", "NL123456789X01"])
def test_btw_bad(raw):
    assert not is_valid_btw_id(normalize_btw_id(raw))
    with pytest.raises(CompanyError) as e:
        ok(btw_id=raw)
    assert e.value.codes == ["INVALID_COMPANY_BTW_ID"]
    assert "NL123456789B01" in e.value.messages[0]


# --- iban ---
@pytest.mark.parametrize("raw", ["NL91ABNA0417164300", "nl91 abna 0417 1643 00"])
def test_iban_ok(raw):
    assert ok(iban=raw).iban == "NL91ABNA0417164300"


def test_iban_bad_checksum():
    with pytest.raises(CompanyError) as e:
        ok(iban="NL91ABNA0417164301")
    assert e.value.codes == ["INVALID_COMPANY_IBAN"]
    assert "controlecijfers" in e.value.messages[0]


def test_iban_nl_wrong_length():
    with pytest.raises(CompanyError):
        ok(iban="NL91ABNA04171643000")


def test_format_iban():
    assert format_iban("NL91ABNA0417164300") == "NL91 ABNA 0417 1643 00"


# --- postal code ---
def test_postal_nl_normalized():
    assert validate_nl_postal_code("1234ab", "NL") == "1234 AB"
    assert ok(postal_code="1234ab").postal_code == "1234 AB"
    assert ok(postal_code=" 1234  AB ").postal_code == "1234 AB"


def test_postal_nl_bad():
    with pytest.raises(CompanyError) as e:
        ok(postal_code="12345")
    assert e.value.messages == [
        "Een Nederlandse postcode bestaat uit 4 cijfers en 2 letters, bijvoorbeeld 1234 AB."
    ]


def test_postal_default_country_is_nl():
    with pytest.raises(CompanyError):
        ok(postal_code="10115")


def test_postal_foreign_passes_and_max_length():
    assert ok(postal_code="10115", country="de").postal_code == "10115"
    with pytest.raises(CompanyError):
        ok(postal_code="1" * 13, country="DE")


# --- names, form, country, email ---
def test_name_required():
    with pytest.raises(CompanyError) as e:
        validate_company_input(CompanyInput(legal_name=" "))
    assert e.value.messages == ["Vul de naam van je bedrijf of je eigen naam in."]
    assert e.value.codes == ["COMPANY_NAME_REQUIRED"]


def test_names_too_long():
    with pytest.raises(CompanyError) as e:
        ok(legal_name="x" * 201, trade_name="y" * 201)
    assert e.value.messages == ["Deze naam is te lang (maximaal 200 tekens). Kort de naam in."] * 2
    assert ok(legal_name="x" * 200).legal_name == "x" * 200


def test_legal_form():
    assert ok().legal_form == "eenmanszaak"
    assert ok(legal_form="vof").legal_form == "vof"
    with pytest.raises(CompanyError) as e:
        ok(legal_form="bv")
    assert e.value.messages == ["Kies eenmanszaak of vof als rechtsvorm."]


def test_country_default_and_bad():
    assert ok().country == "NL"
    assert ok(country="de").country == "DE"
    with pytest.raises(CompanyError):
        ok(country="Nederland")


def test_email():
    assert ok(email="a@b.nl").email == "a@b.nl"
    assert ok(email="").email is None
    with pytest.raises(CompanyError):
        ok(email="geen-email")


def test_optional_empty_become_none():
    n = ok(trade_name="", address_line=" ", city="", phone="")
    assert (n.trade_name, n.address_line, n.city, n.phone) == (None, None, None, None)


def test_all_errors_collected_in_one():
    with pytest.raises(CompanyError) as e:
        validate_company_input(
            CompanyInput(legal_name="", kvk="1", btw_id="x", iban="y", postal_code="z", email="q")
        )
    assert len(e.value.messages) == 6
    assert len(set(e.value.codes)) == 6
