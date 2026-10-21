import time

import pytest
from sqlalchemy import func, select

import app.domain.company as company
from app.domain.company import (
    CompanyInput,
    CompanyProfile,
    format_iban,
    get_company_profile,
    require_company_for_invoice,
    save_company_profile,
)
from app.domain.errors import CompanyError, CompanyIncompleteError
from app.models.company import CompanyProfile as Row

FULL = dict(
    legal_name="Jansen Webdesign",
    address_line="Dorpsstraat 1",
    postal_code="1234ab",
    city="Utrecht",
    kvk="1234 5678",
    btw_id="nl123456789b01",
    iban="nl91 abna 0417 1643 00",
)


def count(session):
    return session.scalar(select(func.count()).select_from(Row))


def test_public_api():
    for name in (
        "CompanyInput", "CompanyProfile", "CompanyError", "CompanyIncompleteError",
        "get_company_profile", "save_company_profile", "require_company_for_invoice", "format_iban",
    ):
        assert hasattr(company, name)


def test_empty_profile(session):
    p = get_company_profile(session)
    assert isinstance(p, CompanyProfile)
    assert p.legal_name is None and p.kvk is None
    assert not p.is_complete_for_invoice
    assert p.missing_for_invoice() == [
        "naam", "adres", "postcode", "plaats", "KvK-nummer", "btw-id", "IBAN",
    ]
    assert count(session) == 0


def test_profile_is_frozen(session):
    with pytest.raises(Exception):
        get_company_profile(session).legal_name = "x"


def test_save_creates_row_id_1(session):
    p = save_company_profile(session, CompanyInput(**FULL))
    session.commit()
    assert session.scalar(select(Row.id)) == 1
    assert p.kvk == "12345678" and p.btw_id == "NL123456789B01"
    assert p.iban == "NL91ABNA0417164300"
    assert p.postal_code == "1234 AB"
    assert p.is_complete_for_invoice and p.missing_for_invoice() == []
    assert p.iban_display == "NL91 ABNA 0417 1643 00"
    assert p.legal_form == "eenmanszaak" and p.country == "NL"
    assert get_company_profile(session) == p


def test_second_save_updates(session):
    save_company_profile(session, CompanyInput(**FULL))
    session.commit()
    first = session.scalar(select(Row.updated_at))
    time.sleep(0.01)
    save_company_profile(session, CompanyInput(**{**FULL, "city": "Zeist"}))
    session.commit()
    assert count(session) == 1
    assert get_company_profile(session).city == "Zeist"
    assert session.scalar(select(Row.updated_at)) > first


def test_partial_save_name_only(session):
    p = save_company_profile(session, CompanyInput(legal_name="Jansen"))
    session.commit()
    assert p.legal_name == "Jansen"
    assert p.missing_for_invoice()[0] == "adres"
    assert p.iban_display == ""


def test_save_invalid_saves_nothing(session):
    with pytest.raises(CompanyError):
        save_company_profile(session, CompanyInput(legal_name="J", kvk="1"))
    assert count(session) == 0


def test_clearing_optional_field_stores_null(session):
    save_company_profile(session, CompanyInput(**FULL, email="a@b.nl"))
    save_company_profile(session, CompanyInput(**FULL, email=""))
    assert get_company_profile(session).email is None


def test_require_incomplete_raises(session):
    save_company_profile(
        session,
        CompanyInput(
            legal_name="J", postal_code="1234 AB", city="X",
            btw_id="NL123456789B01", iban="NL91ABNA0417164300",
        ),
    )
    with pytest.raises(CompanyIncompleteError) as e:
        require_company_for_invoice(session)
    assert e.value.code == "COMPANY_INCOMPLETE"
    assert e.value.message == (
        "Vul eerst je bedrijfsgegevens aan onder Instellingen > Bedrijfsgegevens. "
        "Er ontbreekt: adres, KvK-nummer."
    )


def test_require_empty_raises(session):
    with pytest.raises(CompanyIncompleteError):
        require_company_for_invoice(session)


def test_require_complete_returns(session):
    save_company_profile(session, CompanyInput(**FULL))
    assert require_company_for_invoice(session).legal_name == "Jansen Webdesign"


def test_address_lines(session):
    p = save_company_profile(session, CompanyInput(**FULL))
    assert p.address_lines() == ["Dorpsstraat 1", "1234 AB Utrecht"]
    p = save_company_profile(
        session, CompanyInput(**{**FULL, "country": "DE", "postal_code": "10115", "city": "Berlin"})
    )
    assert p.address_lines() == ["Dorpsstraat 1", "10115 Berlin", "Duitsland"]


def test_address_lines_partial(session):
    assert get_company_profile(session).address_lines() == []
    p = save_company_profile(session, CompanyInput(legal_name="J", city="Utrecht"))
    assert p.address_lines() == ["Utrecht"]


def test_format_iban_exported():
    assert format_iban("NL91ABNA0417164300") == "NL91 ABNA 0417 1643 00"
