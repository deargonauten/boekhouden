"""Company profile persistence. No commit here: the caller commits (like relations)."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.company.profile import CompanyProfile
from app.domain.company.validation import CompanyInput, validate_company_input
from app.domain.errors import CompanyIncompleteError
from app.models.company import CompanyProfile as CompanyRow

_FIELDS = (
    "legal_name", "trade_name", "legal_form", "address_line", "postal_code", "city",
    "country", "kvk", "btw_id", "iban", "email", "phone",
)  # fmt: skip


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_profile(row: CompanyRow | None) -> CompanyProfile:
    if row is None:
        return CompanyProfile()
    return CompanyProfile(**{f: getattr(row, f) for f in _FIELDS})


def get_company_profile(session: Session) -> CompanyProfile:
    """Always returns a profile; fields are None when nothing is stored yet."""
    return _to_profile(session.get(CompanyRow, 1))


def save_company_profile(session: Session, data: CompanyInput) -> CompanyProfile:
    """Validate, then insert the single row (id 1) or update it. Flushes; caller commits."""
    norm = validate_company_input(data)
    now = _now()
    row = session.get(CompanyRow, 1)
    if row is None:
        row = CompanyRow(id=1, created_at=now)
        session.add(row)
    for f in _FIELDS:
        setattr(row, f, getattr(norm, f))
    row.updated_at = now
    session.flush()
    return _to_profile(row)


def require_company_for_invoice(session: Session) -> CompanyProfile:
    """The profile, or CompanyIncompleteError listing what is missing."""
    profile = get_company_profile(session)
    missing = profile.missing_for_invoice()
    if missing:
        raise CompanyIncompleteError(
            "Vul eerst je bedrijfsgegevens aan onder Instellingen > Bedrijfsgegevens. "
            f"Er ontbreekt: {', '.join(missing)}."
        )
    return profile
