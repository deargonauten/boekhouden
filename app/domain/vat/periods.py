"""Btw-aangifte periods (pure): a quarter or a month of a calendar year."""

import calendar
from dataclasses import dataclass
from datetime import date

from app.domain.errors import vat_error

KINDS = ("quarter", "month")
_MONTH_NAMES = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)


@dataclass(frozen=True)
class VatPeriod:
    """A return period: `(year, kind, number)`; kind 'quarter' (1-4) or 'month' (1-12)."""

    year: int
    kind: str
    number: int

    def __post_init__(self) -> None:
        limit = 4 if self.kind == "quarter" else 12
        if (
            self.kind not in KINDS
            or isinstance(self.year, bool) or not isinstance(self.year, int) or not 1900 <= self.year <= 9999
            or isinstance(self.number, bool) or not isinstance(self.number, int) or not 1 <= self.number <= limit
        ):
            raise vat_error("VAT_PERIOD_INVALID")

    @property
    def label(self) -> str:
        """Plain Dutch, e.g. '3e kwartaal 2026' or 'juli 2026'."""
        if self.kind == "quarter":
            return f"{self.number}e kwartaal {self.year}"
        return f"{_MONTH_NAMES[self.number - 1]} {self.year}"

    @property
    def slug(self) -> str:
        """Safe for URLs and filenames, e.g. '2026-Q3' or '2026-M07'."""
        return f"{self.year}-Q{self.number}" if self.kind == "quarter" else f"{self.year}-M{self.number:02d}"


def months(period: VatPeriod) -> list[int]:
    """Month numbers (1-12) covered by the period."""
    if period.kind == "quarter":
        first = (period.number - 1) * 3 + 1
        return [first, first + 1, first + 2]
    return [period.number]


def period_range(period: VatPeriod) -> tuple[date, date]:
    """First and last day (inclusive)."""
    ms = months(period)
    last = ms[-1]
    return date(period.year, ms[0], 1), date(period.year, last, calendar.monthrange(period.year, last)[1])


def deadline(period: VatPeriod) -> date:
    """Last day of the month after the period (weekends and holidays are not adjusted)."""
    end = period_range(period)[1]
    year, month = (end.year + 1, 1) if end.month == 12 else (end.year, end.month + 1)
    return date(year, month, calendar.monthrange(year, month)[1])


def is_overdue(period: VatPeriod, today: date | None = None) -> bool:
    return (today or date.today()) > deadline(period)


def quarter_of(day: date) -> int:
    return (day.month - 1) // 3 + 1


def periods_of_year(year: int, kind: str) -> list[VatPeriod]:
    count = 4 if kind == "quarter" else 12
    return [VatPeriod(year, kind, n) for n in range(1, count + 1)]


def period_for_date(day: date, kind: str) -> VatPeriod:
    return VatPeriod(day.year, kind, quarter_of(day) if kind == "quarter" else day.month)


def previous(period: VatPeriod) -> VatPeriod | None:
    """The period before this one in the same year; None for the first of the year."""
    return None if period.number == 1 else VatPeriod(period.year, period.kind, period.number - 1)


def overlaps(a: VatPeriod, b: VatPeriod) -> bool:
    (a0, a1), (b0, b1) = period_range(a), period_range(b)
    return a0 <= b1 and b0 <= a1
