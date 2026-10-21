import re

import pytest

import app.domain.errors as errors
from app.domain.company import CompanyInput
from app.domain.company.validation import validate_company_input
from app.domain.errors import CompanyError, RelationError

CLASSES = [
    "InvalidCompanyKvkError",
    "InvalidCompanyBtwIdError",
    "InvalidCompanyIbanError",
    "InvalidCompanyPostalCodeError",
    "InvalidCompanyLegalFormError",
    "CompanyNameRequiredError",
    "CompanyNameTooLongError",
    "CompanyIncompleteError",
]


@pytest.mark.parametrize("name", CLASSES)
def test_inherits_company_error(name):
    cls = getattr(errors, name)
    assert issubclass(cls, CompanyError)
    assert issubclass(cls, RelationError)


def test_codes():
    assert CompanyError.code == "COMPANY_ERROR"
    assert errors.InvalidCompanyKvkError.code == "INVALID_COMPANY_KVK"
    assert errors.InvalidCompanyBtwIdError.code == "INVALID_COMPANY_BTW_ID"
    assert errors.InvalidCompanyIbanError.code == "INVALID_COMPANY_IBAN"
    assert errors.CompanyNameRequiredError.code == "COMPANY_NAME_REQUIRED"
    assert errors.CompanyIncompleteError.code == "COMPANY_INCOMPLETE"


def test_combine_returns_company_error():
    a = errors.CompanyNameRequiredError("Vul in.")
    b = errors.InvalidCompanyKvkError("Fout.")
    combined = CompanyError.combine([a, b])
    assert isinstance(combined, CompanyError)
    assert combined.messages == ["Vul in.", "Fout."]


def test_validation_messages_are_plain_dutch():
    with pytest.raises(CompanyError) as e:
        validate_company_input(
            CompanyInput(
                legal_name="x" * 300, legal_form="bv", kvk="1", btw_id="x", iban="y",
                postal_code="z", email="q", country="Nederland",
            )
        )
    assert len(e.value.messages) >= 7
    for m in e.value.messages:
        assert re.search(r"[a-z]{3,} [a-z]{2,}", m)  # sentences, not codes
        assert m.endswith(".")
        assert not re.search(r"[A-Z_]{6,}|Traceback|Error", m)
