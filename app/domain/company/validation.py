"""Pure validation and normalization for the company's own bedrijfsgegevens (no database).

Reuses the relations normalizers/validators and re-wraps their errors as
`CompanyError` with wording aimed at the ondernemer's own data.
"""

import re
from dataclasses import dataclass

from app.domain.errors import (
    CompanyError,
    CompanyNameRequiredError,
    CompanyNameTooLongError,
    InvalidCompanyBtwIdError,
    InvalidCompanyIbanError,
    InvalidCompanyKvkError,
    InvalidCompanyLegalFormError,
    InvalidCompanyPostalCodeError,
    RelationError,
)
from app.domain.relations.validation import (
    NAME_MAX,
    POSTAL_CODE_MAX,
    _clean,
    format_iban,  # noqa: F401  (re-exported)
    is_valid_iban,
    is_valid_kvk,
    normalize_iban,
    normalize_kvk,
    validate_country,
    validate_email,
)

LEGAL_FORMS = ("eenmanszaak", "vof")

_BTW_ID_RE = re.compile(r"^NL[0-9]{9}B[0-9]{2}$")
_NL_POSTAL_RE = re.compile(r"^([0-9]{4})\s*([A-Za-z]{2})$")


# --- BTW-id (Dutch only) ------------------------------------------------------
def normalize_btw_id(raw: str | None) -> str | None:
    raw = _clean(raw)
    return re.sub(r"[\s.\-]", "", raw).upper() or None if raw else None


def is_valid_btw_id(value: str | None) -> bool:
    """Format only (no elfproef); own company is Dutch so NL only."""
    return bool(value) and _BTW_ID_RE.match(value) is not None


def validate_btw_id(raw: str | None) -> str | None:
    value = normalize_btw_id(raw)
    if value is None:
        return None
    if not is_valid_btw_id(value):
        raise InvalidCompanyBtwIdError(
            "Je btw-id ziet eruit als NL123456789B01 (NL, 9 cijfers, de letter B en 2 cijfers). "
            "Controleer het nummer."
        )
    return value


def _validate_kvk(raw: str | None) -> str | None:
    value = normalize_kvk(raw)
    if value is None:
        return None
    if not is_valid_kvk(value):
        raise InvalidCompanyKvkError(
            "Je KvK-nummer bestaat uit 8 cijfers, bijvoorbeeld 12345678. Controleer het nummer."
        )
    return value


def _validate_iban(raw: str | None) -> str | None:
    value = normalize_iban(raw)
    if value is None:
        return None
    if not is_valid_iban(value):
        raise InvalidCompanyIbanError(
            "Dit IBAN klopt niet (de controlecijfers kloppen niet). "
            "Controleer je rekeningnummer, bijvoorbeeld NL91 ABNA 0417 1643 00."
        )
    return value


def validate_nl_postal_code(raw: str | None, country: str | None) -> str | None:
    """NL: 4 digits + 2 letters, stored as `1234 AB`. Other countries: max length only."""
    value = _clean(raw)
    if value is None:
        return None
    if (country or "NL") == "NL":
        m = _NL_POSTAL_RE.match(value)
        if m is None:
            raise InvalidCompanyPostalCodeError(
                "Een Nederlandse postcode bestaat uit 4 cijfers en 2 letters, "
                "bijvoorbeeld 1234 AB."
            )
        return f"{m.group(1)} {m.group(2).upper()}"
    if len(value) > POSTAL_CODE_MAX:
        raise InvalidCompanyPostalCodeError(
            f"Een postcode is maximaal {POSTAL_CODE_MAX} tekens lang. Controleer de postcode."
        )
    return value


# --- full input ----------------------------------------------------------------
@dataclass(frozen=True)
class CompanyInput:
    """Raw values as typed in the form; validated by `validate_company_input`."""

    legal_name: str | None = None
    trade_name: str | None = None
    legal_form: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    kvk: str | None = None
    btw_id: str | None = None
    iban: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class NormalizedCompany:
    legal_name: str
    trade_name: str | None
    legal_form: str
    address_line: str | None
    postal_code: str | None
    city: str | None
    country: str
    kvk: str | None
    btw_id: str | None
    iban: str | None
    email: str | None
    phone: str | None


def validate_company_input(data: CompanyInput) -> NormalizedCompany:
    """Normalize all fields. Raises ONE CompanyError carrying every problem found."""
    errors: list[CompanyError] = []

    def check(fn, *args):
        try:
            return fn(*args)
        except CompanyError as e:
            errors.append(e)
        except RelationError as e:  # relations validators: re-wrap as company errors
            errors.append(CompanyError(e.code, e.message))
        return None

    too_long = "Deze naam is te lang (maximaal %d tekens). Kort de naam in." % NAME_MAX

    name = _clean(data.legal_name)
    if name is None:
        errors.append(
            CompanyNameRequiredError("Vul de naam van je bedrijf of je eigen naam in.")
        )
    elif len(name) > NAME_MAX:
        errors.append(CompanyNameTooLongError(too_long))

    trade_name = _clean(data.trade_name)
    if trade_name is not None and len(trade_name) > NAME_MAX:
        errors.append(CompanyNameTooLongError(too_long))

    legal_form = _clean(data.legal_form) or "eenmanszaak"
    if legal_form not in LEGAL_FORMS:
        errors.append(InvalidCompanyLegalFormError("Kies eenmanszaak of vof als rechtsvorm."))

    country = check(validate_country, data.country)
    postal_code = check(validate_nl_postal_code, data.postal_code, country)
    kvk = check(_validate_kvk, data.kvk)
    btw_id = check(validate_btw_id, data.btw_id)
    iban = check(_validate_iban, data.iban)
    email = check(validate_email, data.email)

    if errors:
        raise CompanyError.combine(errors)

    return NormalizedCompany(
        legal_name=name,
        trade_name=trade_name,
        legal_form=legal_form,
        address_line=_clean(data.address_line),
        postal_code=postal_code,
        city=_clean(data.city),
        country=country,
        kvk=kvk,
        btw_id=btw_id,
        iban=iban,
        email=email,
        phone=_clean(data.phone),
    )
