"""Plain-language labels and suggested defaults, so forms can preselect sensible values."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, FiscalYear, Journal

ACCOUNT_TYPE_LABELS: dict[str, str] = {
    "asset": "Wat je bezit (Activa)",
    "liability": "Wat je schuldig bent (Passiva)",
    "equity": "Eigen vermogen",
    "revenue": "Opbrengsten (wat je verdient)",
    "expense": "Kosten (wat je uitgeeft)",
}

JOURNAL_TYPE_LABELS: dict[str, str] = {
    "verkoop": "Verkoop (verkoopfacturen)",
    "inkoop": "Inkoop (inkoopfacturen)",
    "bank": "Bank (bankrekening)",
    "kas": "Kas (contant geld)",
    "memoriaal": "Memoriaal (overige boekingen)",
}

_MIN_CODE = 1000
_MAX_CODE = 9999


def suggest_account_code(session: Session, type: str) -> str:
    """A free 4-digit account number in the area of the seeded accounts of `type`.

    Highest existing code of the type + 10, rounded down to a multiple of 10. If that is
    out of range or taken, the first unused code above the type's lowest code.
    """
    taken = {int(c) for c in session.scalars(select(Account.code)) if c.isdigit()}
    own = sorted(
        int(c) for c in session.scalars(select(Account.code).where(Account.type == type)) if c.isdigit()
    )
    if own:
        candidate = (own[-1] + 10) // 10 * 10
        if candidate <= _MAX_CODE and candidate not in taken:
            return f"{candidate:04d}"
    start = own[0] if own else _MIN_CODE
    for n in range(start + 1, _MAX_CODE + 1):
        if n not in taken:
            return f"{n:04d}"
    for n in range(_MIN_CODE, start + 1):
        if n not in taken:
            return f"{n:04d}"
    for n in range(0, _MIN_CODE):
        if n not in taken:
            return f"{n:04d}"
    raise ValueError("Alle rekeningnummers van 4 cijfers zijn in gebruik.")


def suggest_fiscal_year(session: Session, today: date) -> int:
    """Smallest year >= today.year that has no boekjaar yet."""
    existing = set(session.scalars(select(FiscalYear.year)))
    year = today.year
    while year in existing:
        year += 1
    return year


def default_journal_id(session: Session, journal_type: str) -> int | None:
    """Id of the first active journal of `journal_type`, or None."""
    return session.scalar(
        select(Journal.id)
        .where(Journal.type == journal_type, Journal.is_active.is_(True))
        .order_by(Journal.id)
        .limit(1)
    )
