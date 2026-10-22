"""Pure validation and normalization for relations (no database).

`normalize_*` only tidy a value (never raise); `is_valid_*` check an already
normalized value; `validate_*` do both and raise a `RelationError` with a
plain-Dutch message. Empty input becomes None everywhere.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.domain.errors import (
    InvalidBtwNumberError,
    InvalidCountryError,
    InvalidEmailError,
    InvalidIbanError,
    InvalidKvkError,
    InvalidNameError,
    InvalidPostalCodeError,
    NameRequiredError,
    RelationError,
    RoleRequiredError,
)

NAME_MAX = 200
PAYMENT_TERM_MAX = 365
POSTAL_CODE_MAX = 12

_KVK_RE = re.compile(r"^[0-9]{8}$")
_BTW_NL_RE = re.compile(r"^NL[0-9]{9}B[0-9]{2}$")
_BTW_FOREIGN_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{2,12}$")
_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _clean(value: str | None) -> str | None:
    """Trim; empty becomes None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


# --- KvK ---------------------------------------------------------------------
def normalize_kvk(raw: str | None) -> str | None:
    raw = _clean(raw)
    return re.sub(r"[\s.\-]", "", raw) or None if raw else None


def is_valid_kvk(value: str | None) -> bool:
    return bool(value) and _KVK_RE.match(value) is not None


def validate_kvk(raw: str | None) -> str | None:
    value = normalize_kvk(raw)
    if value is None:
        return None
    if not is_valid_kvk(value):
        raise InvalidKvkError(
            "Een KvK-nummer bestaat uit 8 cijfers, bijvoorbeeld 12345678. Controleer het nummer."
        )
    return value


# --- BTW-nummer ---------------------------------------------------------------
def normalize_btw_number(raw: str | None) -> str | None:
    raw = _clean(raw)
    return re.sub(r"[\s.\-]", "", raw).upper() or None if raw else None


def is_valid_btw_number(value: str | None) -> bool:
    """Format only (no elfproef). NL strict; other two-letter prefixes loose."""
    if not value:
        return False
    if value.startswith("NL"):
        return _BTW_NL_RE.match(value) is not None
    return _BTW_FOREIGN_RE.match(value) is not None


def validate_btw_number(raw: str | None) -> str | None:
    value = normalize_btw_number(raw)
    if value is None:
        return None
    if not is_valid_btw_number(value):
        raise InvalidBtwNumberError(
            "Een Nederlands btw-nummer ziet eruit als NL123456789B01 "
            "(NL, 9 cijfers, B, 2 cijfers). Controleer het nummer."
        )
    return value


# --- IBAN ---------------------------------------------------------------------
def normalize_iban(raw: str | None) -> str | None:
    raw = _clean(raw)
    return re.sub(r"\s+", "", raw).upper() or None if raw else None


def is_valid_iban(value: str | None) -> bool:
    if not value or _IBAN_RE.match(value) is None:
        return False
    if value.startswith("NL") and len(value) != 18:
        return False
    rearranged = value[4:] + value[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def validate_iban(raw: str | None) -> str | None:
    value = normalize_iban(raw)
    if value is None:
        return None
    if not is_valid_iban(value):
        raise InvalidIbanError(
            "Dit IBAN klopt niet (controlecijfers kloppen niet). "
            "Controleer het rekeningnummer, bijvoorbeeld NL91 ABNA 0417 1643 00."
        )
    return value


def format_iban(value: str | None) -> str:
    """Display format: groups of four. Stored values stay unspaced."""
    if not value:
        return ""
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


# --- email, postal code, country ---------------------------------------------
def normalize_email(raw: str | None) -> str | None:
    return _clean(raw)


def validate_email(raw: str | None) -> str | None:
    value = normalize_email(raw)
    if value is None:
        return None
    if _EMAIL_RE.match(value) is None:
        raise InvalidEmailError(
            "Dit e-mailadres klopt niet. Controleer het adres, bijvoorbeeld naam@bedrijf.nl."
        )
    return value


def validate_postal_code(raw: str | None) -> str | None:
    value = _clean(raw)
    if value is not None and len(value) > POSTAL_CODE_MAX:
        raise InvalidPostalCodeError(
            f"Een postcode is maximaal {POSTAL_CODE_MAX} tekens lang. Controleer de postcode."
        )
    return value


def validate_country(raw: str | None) -> str:
    value = _clean(raw)
    if value is None:
        return "NL"
    value = value.upper()
    if _COUNTRY_RE.match(value) is None:
        raise InvalidCountryError(
            "Een land vul je in als code van twee letters, bijvoorbeeld NL of DE. Controleer het land."
        )
    return value


def validate_payment_term(raw: "str | int | None") -> int | None:
    """Betaaltermijn in days for a klant: empty is None (the invoice then uses 30 days), else 0..365."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    text = str(raw).strip()
    if not re.fullmatch(r"\d{1,3}", text) or int(text) > PAYMENT_TERM_MAX:
        raise RelationError(
            "INVALID_PAYMENT_TERM",
            f"De betaaltermijn is een aantal dagen tussen 0 en {PAYMENT_TERM_MAX}. "
            "Vul bijvoorbeeld 30 in, of laat het leeg voor de standaard van 30 dagen.",
        )
    return int(text)


# --- names ---------------------------------------------------------------------
_LEGAL_TOKENS = {
    ("bv",), ("b", "v"), ("nv",), ("vof",), ("v", "o", "f"), ("cv",), ("eenmanszaak",),
    ("ltd",), ("llc",), ("inc",), ("gmbh",), ("sarl",), ("bvba",), ("sa",),
}  # fmt: skip
_LEADING_ARTICLES = {"de", "het", "the"}


def normalize_name(name: str | None) -> str:
    """Comparison key for names; see spec section 26."""
    plain = (name or "").strip().casefold()
    text = unicodedata.normalize("NFKD", plain)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("&", " en ")
    text = re.sub(r"[.'`’]", "", text)  # B.V. -> bv, Bakker's -> bakkers
    text = re.sub(r"[^0-9a-z]+", " ", text)
    tokens = text.split()
    changed = True
    while changed and tokens:
        changed = False
        for legal in _LEGAL_TOKENS:
            n = len(legal)
            if len(tokens) >= n and tuple(tokens[-n:]) == legal:
                tokens = tokens[:-n]
                changed = True
                break
    if tokens and tokens[0] in _LEADING_ARTICLES:
        tokens = tokens[1:]
    return " ".join(tokens) or " ".join(plain.split())


# --- full input ------------------------------------------------------------------
@dataclass(frozen=True)
class ContactInput:
    """Raw values as typed in the form (or extracted); validated by `validate_contact_input`."""

    name: str | None = None
    is_customer: bool = False
    is_supplier: bool = False
    kvk: str | None = None
    btw_number: str | None = None
    iban: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    payment_term_days: "str | int | None" = None  # betaaltermijn voor klanten, in dagen


@dataclass(frozen=True)
class NormalizedContact:
    name: str
    name_key: str
    is_customer: bool
    is_supplier: bool
    kvk: str | None
    btw_number: str | None
    iban: str | None
    address_line: str | None
    postal_code: str | None
    city: str | None
    country: str
    email: str | None
    phone: str | None
    notes: str | None
    payment_term_days: int | None = None


def validate_contact_input(data: ContactInput) -> NormalizedContact:
    """Normalize all fields. Raises ONE RelationError carrying every problem found."""
    errors: list[RelationError] = []

    def check(fn, value):
        try:
            return fn(value)
        except RelationError as e:
            errors.append(e)
            return None

    name = _clean(data.name)
    if name is None:
        errors.append(NameRequiredError("Vul de naam van de relatie in."))
    elif len(name) > NAME_MAX:
        errors.append(
            InvalidNameError(
                f"Deze naam is te lang (maximaal {NAME_MAX} tekens). Kort de naam in."
            )
        )
    if not (data.is_customer or data.is_supplier):
        errors.append(RoleRequiredError("Kies of dit een klant, een leverancier of allebei is."))

    kvk = check(validate_kvk, data.kvk)
    btw = check(validate_btw_number, data.btw_number)
    iban = check(validate_iban, data.iban)
    email = check(validate_email, data.email)
    postal_code = check(validate_postal_code, data.postal_code)
    country = check(validate_country, data.country)
    payment_term = check(validate_payment_term, data.payment_term_days)

    if errors:
        raise RelationError.combine(errors)

    return NormalizedContact(
        name=name,
        name_key=normalize_name(name),
        is_customer=bool(data.is_customer),
        is_supplier=bool(data.is_supplier),
        kvk=kvk,
        btw_number=btw,
        iban=iban,
        address_line=_clean(data.address_line),
        postal_code=postal_code,
        city=_clean(data.city),
        country=country,
        email=email,
        phone=_clean(data.phone),
        notes=_clean(data.notes),
        payment_term_days=payment_term,
    )
