"""Filing (indienen) of a btw-aangifte and locking of its periods.

STUB (public API); implementation follows. `ReturnSnapshot` is the frozen contract with Part C.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.domain.vat.icp import IcpRow, IcpUnassigned
from app.domain.vat.periods import VatPeriod
from app.domain.vat.report import RubriekLine, VatWarning


@dataclass
class ReturnSnapshot:
    """Everything an export needs; live for a concept, stored JSON for an ingediende aangifte."""

    period: VatPeriod
    status: str  # 'concept' | 'ingediend'
    company_name: str
    btw_id: str | None
    lines: list[RubriekLine]
    totals: dict[str, int]  # '5a', '5b', '5c', '5g'
    icp: list[IcpRow]
    icp_unassigned: list[IcpUnassigned]
    warnings: list[VatWarning]
    filed_on: date | None
    reference: str | None
    is_concept: bool


@dataclass(frozen=True)
class ReturnRow:
    """One line of the overview page."""

    period: VatPeriod
    status: str  # 'niet_gestart' | 'concept' | 'ingediend'
    deadline: date
    overdue: bool
    total_cents: int | None
    direction: str | None
    kor: str  # 'none' | 'partial' | 'full'
    filed_on: date | None = None


@dataclass(frozen=True)
class FiledReturn:
    period: VatPeriod
    filed_on: date
    filed_at: datetime
    reference: str | None
    total_cents: int
    snapshot: ReturnSnapshot


def list_returns(session: Session, year: int, kind: str, *, today: date | None = None) -> list[ReturnRow]:
    raise NotImplementedError


def get_return(session: Session, period: VatPeriod) -> FiledReturn | None:
    raise NotImplementedError


def get_snapshot(session: Session, period: VatPeriod, *, today: date | None = None) -> ReturnSnapshot:
    raise NotImplementedError


def file_vat_return(
    session: Session, vat_period: VatPeriod, *, filed_on: date, reference: str | None = None,
    today: date | None = None,
) -> FiledReturn:
    raise NotImplementedError
