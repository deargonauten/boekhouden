"""DB-using relations service.

Functions flush but never commit; the caller (route handler / test) commits on
success and rolls back on exception. There is deliberately no delete function:
relations are archived (`set_contact_active`) so old bookings keep their link.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import (
    ContactNotFoundError,
    DuplicateBtwNumberError,
    DuplicateIbanError,
    DuplicateKvkError,
    RelationError,
)
from app.domain.relations.validation import (
    ContactInput,
    NormalizedContact,
    normalize_btw_number,
    normalize_iban,
    normalize_kvk,
    validate_contact_input,
)
from app.models import Contact

Role = Literal["customer", "supplier"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _duplicate_error(field: str, other_name: str) -> RelationError:
    # Literal messages (not f-string variables) so the message lint can read them.
    if field == "kvk":
        return DuplicateKvkError(
            f"Er bestaat al een relatie met dit KvK-nummer: {other_name}. "
            "Open die relatie in plaats van een nieuwe aan te maken."
        )
    if field == "btw_number":
        return DuplicateBtwNumberError(
            f"Er bestaat al een relatie met dit btw-nummer: {other_name}. "
            "Open die relatie in plaats van een nieuwe aan te maken."
        )
    return DuplicateIbanError(
        f"Er bestaat al een relatie met dit IBAN: {other_name}. "
        "Open die relatie in plaats van een nieuwe aan te maken."
    )


def _find_duplicates(
    session: Session, norm: NormalizedContact, exclude_id: int | None
) -> list[RelationError]:
    errors = []
    for field in ("kvk", "btw_number", "iban"):
        value = getattr(norm, field)
        if value is None:
            continue
        stmt = select(Contact).where(getattr(Contact, field) == value)
        if exclude_id is not None:
            stmt = stmt.where(Contact.id != exclude_id)
        other = session.scalars(stmt).first()
        if other is not None:
            errors.append(_duplicate_error(field, other.name))
    return errors


def _write_mapping_duplicates(
    session: Session, norm: NormalizedContact, exclude_id: int | None, write: Callable[[], None]
) -> None:
    """Run `write` and flush; a unique-index violation becomes the named duplicate error.

    No savepoint (pysqlite would commit on release), so after this error the
    session is in a failed state and the caller must roll back, as it does for
    every service error.
    """
    try:
        write()
        session.flush()
    except IntegrityError as exc:
        text = str(exc.orig)
        for field in ("kvk", "btw_number", "iban"):
            if f"contact.{field}" in text:
                value = getattr(norm, field)
                stmt = select(Contact).where(getattr(Contact, field) == value)
                if exclude_id is not None:
                    stmt = stmt.where(Contact.id != exclude_id)
                session.rollback()
                other = session.scalars(stmt).first()
                raise _duplicate_error(field, other.name if other else "een andere relatie") from exc
        raise


def _apply(contact: Contact, norm: NormalizedContact) -> None:
    contact.name = norm.name
    contact.name_key = norm.name_key  # the single place name_key is (re)computed
    contact.is_customer = norm.is_customer
    contact.is_supplier = norm.is_supplier
    contact.kvk = norm.kvk
    contact.btw_number = norm.btw_number
    contact.iban = norm.iban
    contact.address_line = norm.address_line
    contact.postal_code = norm.postal_code
    contact.city = norm.city
    contact.country = norm.country
    contact.email = norm.email
    contact.phone = norm.phone
    contact.notes = norm.notes


def get_contact(session: Session, contact_id: int) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise ContactNotFoundError(
            "Deze relatie bestaat niet (meer). Ga terug naar het overzicht en kies een relatie uit de lijst."
        )
    return contact


def create_contact(session: Session, data: ContactInput) -> Contact:
    norm = validate_contact_input(data)
    duplicates = _find_duplicates(session, norm, None)
    if duplicates:
        raise RelationError.combine(duplicates)
    now = _now()
    contact = Contact(is_active=True, created_at=now, updated_at=now)

    def write() -> None:
        _apply(contact, norm)
        session.add(contact)

    _write_mapping_duplicates(session, norm, None, write)
    return contact


def update_contact(session: Session, contact_id: int, data: ContactInput) -> Contact:
    contact = get_contact(session, contact_id)
    norm = validate_contact_input(data)
    duplicates = _find_duplicates(session, norm, contact.id)
    if duplicates:
        raise RelationError.combine(duplicates)

    def write() -> None:
        _apply(contact, norm)
        contact.updated_at = _now()

    _write_mapping_duplicates(session, norm, contact.id, write)
    return contact


def set_contact_active(session: Session, contact_id: int, active: bool) -> Contact:
    contact = get_contact(session, contact_id)
    contact.is_active = active
    contact.updated_at = _now()
    session.flush()
    return contact


def _matches(contact: Contact, q: str) -> bool:
    needle = q.strip().casefold()
    compact = normalize_iban(q) or ""  # identifiers are stored without spaces/dots/hyphens
    fields = [contact.name, contact.city]
    if needle and any(f and needle in f.casefold() for f in fields):
        return True
    if needle and any(f and needle in f.casefold() for f in (contact.kvk, contact.btw_number, contact.iban)):
        return True
    ids = [
        (contact.kvk, normalize_kvk(q)),
        (contact.btw_number, normalize_btw_number(q)),
        (contact.iban, compact),
    ]
    return any(stored and part and part in stored for stored, part in ids)


def list_contacts(
    session: Session,
    *,
    role: Role | None = None,
    q: str | None = None,
    include_archived: bool = False,
) -> list[Contact]:
    """Relations sorted by name_key. `role` is "customer" or "supplier" (None = all)."""
    stmt = select(Contact).order_by(Contact.name_key, Contact.id)
    if role == "customer":
        stmt = stmt.where(Contact.is_customer.is_(True))
    elif role == "supplier":
        stmt = stmt.where(Contact.is_supplier.is_(True))
    if not include_archived:
        stmt = stmt.where(Contact.is_active.is_(True))
    contacts = list(session.scalars(stmt))
    if q and q.strip():
        contacts = [c for c in contacts if _matches(c, q)]
    return contacts
