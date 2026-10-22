"""ICP-opgaaf (EU sales per klant). STUB (public API); implementation follows."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.domain.vat.report import VatWarning


@dataclass(frozen=True)
class IcpRow:
    country: str  # landcode, e.g. 'DE'
    btw_number: str  # without the landcode prefix; '' when unknown
    goederen_cents: int
    diensten_cents: int
    driehoek_cents: int = 0  # not supported, always 0
    contact_id: int | None = None
    name: str | None = None
    issue: str | None = None  # plain-Dutch fix when the row is incomplete ("Onvolledig")
    entry_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class IcpUnassigned:
    """An EU-sale entry without a klant ('Nog geen klant gekoppeld')."""

    entry_id: int
    entry_number: str
    booking_date: date
    description: str
    goederen_cents: int
    diensten_cents: int


@dataclass
class IcpReport:
    period_start: date
    period_end: date
    rows: list[IcpRow] = field(default_factory=list)  # complete and incomplete (issue set)
    unassigned: list[IcpUnassigned] = field(default_factory=list)
    warnings: list[VatWarning] = field(default_factory=list)


def build_icp(session: Session, start: date, end: date) -> IcpReport:
    raise NotImplementedError


def couple_entry_contact(session: Session, entry_id: int, contact_id: int) -> None:
    raise NotImplementedError


def suggest_contact(session: Session, entry_id: int):
    raise NotImplementedError
