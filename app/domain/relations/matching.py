"""Match-or-create for contacts found by (future) invoice extraction.

Extracted data is unreliable, so nothing here raises on bad values: invalid
identifiers are ignored and reported as Dutch warnings. The session is
flushed, never committed (the caller owns the transaction).
"""

from dataclasses import dataclass
from typing import Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import RelationError
from app.domain.relations.service import _now, create_contact
from app.domain.relations.validation import (
    NAME_MAX,
    ContactInput,
    normalize_name,
    validate_btw_number,
    validate_country,
    validate_email,
    validate_iban,
    validate_kvk,
    validate_postal_code,
)
from app.models import Contact

Status = Literal["matched", "created", "ambiguous", "not_found"]
MatchedOn = Literal["btw_number", "kvk", "iban", "name"]

# Matching priority; each entry: (field, label inside a sentence)
_KEYS: tuple[tuple[str, str], ...] = (
    ("btw_number", "btw-nummer"),
    ("kvk", "KvK-nummer"),
    ("iban", "IBAN"),
)
_LABELS = dict(_KEYS)
_ENRICH_TEXT_FIELDS = ("address_line", "postal_code", "city", "email", "phone")


@dataclass(frozen=True)
class ExtractedContact:
    """Raw supplier/customer data as extracted from a document."""

    name: str | None = None
    kvk: str | None = None
    btw_number: str | None = None
    iban: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class MatchResult:
    contact: Contact | None
    status: Status
    matched_on: MatchedOn | None = None
    candidates: tuple[Contact, ...] = ()
    warnings: tuple[str, ...] = ()


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _safe(
    validator: Callable[[str | None], str | None],
    raw: str | None,
    describe: str,
    warnings: list[str],
) -> str | None:
    """Validated value, or None plus a warning when the raw value is unusable."""
    if _blank(raw):
        return None
    try:
        return validator(raw)
    except RelationError:
        warnings.append(f"{describe} '{raw.strip()}' op de factuur is ongeldig en is genegeerd.")
        return None


def _owner(session: Session, field: str, value: str, exclude_id: int) -> Contact | None:
    stmt = select(Contact).where(getattr(Contact, field) == value, Contact.id != exclude_id)
    return session.scalars(stmt).first()


def _enrich(
    session: Session,
    contact: Contact,
    values: dict[str, str | None],
    role: str,
    already_warned: set[str],
    warnings: list[str],
) -> None:
    changed = False
    for field, _label in _KEYS:
        value = values[field]
        if value is None or getattr(contact, field) is not None:
            continue
        other = _owner(session, field, value, contact.id)
        if other is not None:
            if field not in already_warned:
                warnings.append(
                    f"Het {_LABELS[field]} op de factuur hoort bij {other.name} en is "
                    f"niet overgenomen bij {contact.name}. Controleer of dit dezelfde relatie is."
                )
            continue
        setattr(contact, field, value)
        changed = True
    for field in _ENRICH_TEXT_FIELDS:
        value = values[field]
        if value is not None and _blank(getattr(contact, field)):
            setattr(contact, field, value)
            changed = True
    flag = "is_supplier" if role == "supplier" else "is_customer"
    if not getattr(contact, flag):
        setattr(contact, flag, True)
        changed = True
    if changed:
        contact.updated_at = _now()
        session.flush()


def match_or_create_contact(
    session: Session,
    data: ExtractedContact,
    role: Literal["supplier", "customer"],
    *,
    create: bool = True,
) -> MatchResult:
    warnings: list[str] = []

    values: dict[str, str | None] = {
        "btw_number": _safe(validate_btw_number, data.btw_number, "Het btw-nummer", warnings),
        "kvk": _safe(validate_kvk, data.kvk, "Het KvK-nummer", warnings),
        "iban": _safe(validate_iban, data.iban, "Het IBAN", warnings),
        "email": _safe(validate_email, data.email, "Het e-mailadres", warnings),
        "postal_code": _safe(validate_postal_code, data.postal_code, "De postcode", warnings),
        "address_line": (data.address_line or "").strip() or None,
        "city": (data.city or "").strip() or None,
        "phone": (data.phone or "").strip() or None,
    }
    country = _safe(validate_country, data.country, "Het land", warnings)
    name = " ".join((data.name or "").split())[:NAME_MAX].strip()

    # 1-3: identifiers, active and archived contacts alike.
    hits: dict[str, Contact] = {}
    for field, _label in _KEYS:
        value = values[field]
        if value is not None:
            found = session.scalars(select(Contact).where(getattr(Contact, field) == value)).first()
            if found is not None:
                hits[field] = found

    if hits:
        first_field = next(f for f, _ in _KEYS if f in hits)
        contact = hits[first_field]
        warned: set[str] = set()
        for field, _label in _KEYS:
            other = hits.get(field)
            if other is not None and other.id != contact.id:
                warned.add(field)
                warnings.append(
                    f"Het {_LABELS[field]} op de factuur hoort bij {other.name}, maar het "
                    f"{_LABELS[first_field]} hoort bij {contact.name}. "
                    "Controleer of dit dezelfde relatie is."
                )
        if not contact.is_active:
            contact.is_active = True
            contact.updated_at = _now()
            warnings.append(f"Relatie {contact.name} was gearchiveerd en is weer actief gemaakt.")
        _enrich(session, contact, values, role, warned, warnings)
        return MatchResult(contact, "matched", first_field, (), tuple(warnings))

    # 4: normalized name, active contacts only.
    if name:
        key = normalize_name(name)
        candidates = list(
            session.scalars(
                select(Contact)
                .where(Contact.name_key == key, Contact.is_active.is_(True))
                .order_by(Contact.id)
            )
        )
        if len(candidates) == 1:
            contact = candidates[0]
            _enrich(session, contact, values, role, set(), warnings)
            return MatchResult(contact, "matched", "name", (), tuple(warnings))
        if len(candidates) > 1:
            return MatchResult(None, "ambiguous", None, tuple(candidates), tuple(warnings))

    if not create or not name:
        if create and not name:
            warnings.append(
                "Er is geen naam of bedrijfsgegeven gevonden om een relatie op aan te maken."
            )
        return MatchResult(None, "not_found", None, (), tuple(warnings))

    contact = create_contact(
        session,
        ContactInput(
            name=name,
            is_customer=role == "customer",
            is_supplier=role == "supplier",
            kvk=values["kvk"],
            btw_number=values["btw_number"],
            iban=values["iban"],
            address_line=values["address_line"],
            postal_code=values["postal_code"],
            city=values["city"],
            country=country,
            email=values["email"],
            phone=values["phone"],
        ),
    )
    return MatchResult(contact, "created", None, (), tuple(warnings))
