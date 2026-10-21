import pytest

from app.domain.errors import LedgerError, RelationError
from app.domain.relations.validation import (
    ContactInput,
    NormalizedContact,
    format_iban,
    is_valid_btw_number,
    is_valid_iban,
    is_valid_kvk,
    normalize_btw_number,
    normalize_email,
    normalize_iban,
    normalize_kvk,
    normalize_name,
    validate_btw_number,
    validate_contact_input,
    validate_email,
    validate_iban,
    validate_kvk,
)


def _raises(fn, value, code):
    with pytest.raises(RelationError) as exc:
        fn(value)
    assert exc.value.code == code
    assert isinstance(exc.value, LedgerError)
    return exc.value


# --- KvK ---
@pytest.mark.parametrize(
    "raw,expected",
    [("12345678", "12345678"), (" 1234 5678 ", "12345678"), ("12.34.56.78", "12345678"), ("1234-5678", "12345678")],
)
def test_kvk_valid(raw, expected):
    assert validate_kvk(raw) == expected
    assert normalize_kvk(raw) == expected
    assert is_valid_kvk(expected)


@pytest.mark.parametrize("raw", ["1234567", "123456789", "1234567a", "abcdefgh"])
def test_kvk_invalid(raw):
    err = _raises(validate_kvk, raw, "INVALID_KVK")
    assert err.message == "Een KvK-nummer bestaat uit 8 cijfers, bijvoorbeeld 12345678. Controleer het nummer."


def test_kvk_empty_is_none():
    assert validate_kvk("") is None
    assert validate_kvk("  ") is None
    assert validate_kvk(None) is None


# --- BTW ---
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NL123456789B01", "NL123456789B01"),
        ("nl 1234.56.789 b01", "NL123456789B01"),
        ("NL-123456789-B01", "NL123456789B01"),
        ("DE123456789", "DE123456789"),
        ("be 0123.456.789", "BE0123456789"),
        ("FR12345678901", "FR12345678901"),
    ],
)
def test_btw_valid(raw, expected):
    assert validate_btw_number(raw) == expected
    assert normalize_btw_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["NL123456789B1", "NL12345678B01", "NL123456789X01", "123456789B01", "N", "12", "DE", "D!123", "NL"],
)
def test_btw_invalid(raw):
    err = _raises(validate_btw_number, raw, "INVALID_BTW_NUMBER")
    assert "NL123456789B01" in err.message
    assert not is_valid_btw_number(normalize_btw_number(raw))


def test_btw_empty_is_none():
    assert validate_btw_number("") is None


def test_btw_no_elfproef():
    # Modern NL numbers need not pass the 11-proof; format only.
    assert validate_btw_number("NL000000000B00") == "NL000000000B00"


# --- IBAN ---
@pytest.mark.parametrize("iban", ["NL91ABNA0417164300", "DE89370400440532013000", "BE68539007547034"])
def test_iban_valid(iban):
    assert validate_iban(iban) == iban
    assert is_valid_iban(iban)


def test_iban_normalizes():
    assert validate_iban("nl91 abna 0417 1643 00") == "NL91ABNA0417164300"
    assert normalize_iban(" nl91abna0417164300 ") == "NL91ABNA0417164300"


@pytest.mark.parametrize(
    "iban",
    [
        "NL91ABNA0417164301",  # flipped check digit
        "NL92ABNA0417164300",
        "NL91ABNA041716430",  # too short
        "NL91ABNA04171643000",  # NL too long
        "91ABNA0417164300",
        "XX",
        "NL91ABNA0417-164300",
    ],
)
def test_iban_invalid(iban):
    err = _raises(validate_iban, iban, "INVALID_IBAN")
    assert "NL91 ABNA 0417 1643 00" in err.message


def test_iban_nl_length_enforced():
    # Valid mod-97 but 20 characters for NL: must fail.
    body = "ABNA" + "0" * 12
    digits = "".join(str(int(c, 36)) for c in body + "NL00")
    check = 98 - int(digits) % 97
    iban = f"NL{check:02d}{body}"
    assert len(iban) == 20
    assert not is_valid_iban(iban)
    # Same construction for DE (no NL length rule) is accepted.
    digits = "".join(str(int(c, 36)) for c in body + "DE00")
    check = 98 - int(digits) % 97
    assert is_valid_iban(f"DE{check:02d}{body}")


def test_iban_empty_is_none():
    assert validate_iban(None) is None


def test_format_iban():
    assert format_iban("NL91ABNA0417164300") == "NL91 ABNA 0417 1643 00"
    assert format_iban("DE89370400440532013000") == "DE89 3704 0044 0532 0130 00"
    assert format_iban(None) == ""
    assert format_iban("") == ""


# --- email ---
def test_email():
    assert validate_email(" a@b.nl ") == "a@b.nl"
    assert validate_email("") is None
    assert normalize_email("  ") is None
    for bad in ["abc", "a@b", "a b@c.nl", "@b.nl", "a@@b.nl"]:
        _raises(validate_email, bad, "INVALID_EMAIL")


# --- name key ---
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jansen & Zn. B.V.", "jansen en zn"),
        ("jansen en zn", "jansen en zn"),
        ("Café De Pijp", "cafe de pijp"),
        ("Cafe de Pijp", "cafe de pijp"),
        ("De Bakker", "bakker"),
        ("Het Fietsatelier", "fietsatelier"),
        ("The Print Shop Ltd", "print shop"),
        ("Acme Holding B.V.", "acme holding"),
        ("Acme VOF", "acme"),
        ("Acme V.O.F.", "acme"),
        ("Müller GmbH", "muller"),
        ("Foo B.V. N.V.", "foo"),
        ("  Extra   Spaties  ", "extra spaties"),
        ("A-B/C", "a b c"),
        ("B.V.", "b.v."),
        ("De BV", "de bv"),
        ("Bakker's Bloemen", "bakkers bloemen"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_normalize_name_equalities():
    assert normalize_name("Jansen & Zn. B.V.") == normalize_name("jansen en zn")
    assert normalize_name("Café De Pijp") == normalize_name("Cafe de Pijp")


# --- full input ---
def test_contact_input_normalizes_and_empty_to_none():
    n = validate_contact_input(
        ContactInput(
            name="  Jansen & Zn. B.V. ",
            is_supplier=True,
            kvk="1234 5678",
            btw_number="nl123456789b01",
            iban="nl91 abna 0417 1643 00",
            address_line="",
            postal_code=" 1011 AB ",
            city="Amsterdam",
            country="",
            email="",
            phone=" ",
            notes="",
        )
    )
    assert isinstance(n, NormalizedContact)
    assert n.name == "Jansen & Zn. B.V."
    assert n.name_key == "jansen en zn"
    assert n.kvk == "12345678"
    assert n.btw_number == "NL123456789B01"
    assert n.iban == "NL91ABNA0417164300"
    assert n.address_line is None and n.email is None and n.phone is None and n.notes is None
    assert n.postal_code == "1011 AB"
    assert n.country == "NL"
    assert n.is_supplier and not n.is_customer


def test_contact_input_minimal():
    n = validate_contact_input(ContactInput(name="X", is_customer=True))
    assert n.kvk is None and n.country == "NL"


def test_country_uppercased_and_checked():
    n = validate_contact_input(ContactInput(name="X", is_customer=True, country="de"))
    assert n.country == "DE"
    with pytest.raises(RelationError) as exc:
        validate_contact_input(ContactInput(name="X", is_customer=True, country="Duitsland"))
    assert exc.value.code == "INVALID_COUNTRY"


def test_name_required_and_too_long():
    for name in ["", "   ", None]:
        with pytest.raises(RelationError) as exc:
            validate_contact_input(ContactInput(name=name, is_supplier=True))
        assert exc.value.code == "NAME_REQUIRED"
    with pytest.raises(RelationError) as exc:
        validate_contact_input(ContactInput(name="x" * 201, is_supplier=True))
    assert exc.value.code == "INVALID_NAME"
    validate_contact_input(ContactInput(name="x" * 200, is_supplier=True))


def test_role_required():
    with pytest.raises(RelationError) as exc:
        validate_contact_input(ContactInput(name="X"))
    assert exc.value.code == "ROLE_REQUIRED"
    assert exc.value.message == "Kies of dit een klant, een leverancier of allebei is."


def test_postal_code_max_12():
    with pytest.raises(RelationError) as exc:
        validate_contact_input(ContactInput(name="X", is_customer=True, postal_code="1" * 13))
    assert exc.value.code == "INVALID_POSTAL_CODE"


def test_all_errors_collected():
    with pytest.raises(RelationError) as exc:
        validate_contact_input(
            ContactInput(name="", kvk="12", btw_number="NL1", iban="NL00", email="x")
        )
    e = exc.value
    assert set(e.codes) == {
        "NAME_REQUIRED",
        "ROLE_REQUIRED",
        "INVALID_KVK",
        "INVALID_BTW_NUMBER",
        "INVALID_IBAN",
        "INVALID_EMAIL",
    }
    assert len(e.messages) == 6
    assert str(e) == " ".join(e.messages)
    assert all(isinstance(x, RelationError) for x in e.errors)
