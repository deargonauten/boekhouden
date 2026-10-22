"""BTW-aangifte settings: frequency (kwartaal/maand) and KOR (kleineondernemersregeling)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import vat_error
from app.domain.vat.periods import VatPeriod, period_range
from app.models import VatReturn, VatSetting

KOR_LIMIT_CENTS = 2_000_000  # information only, never enforced
FREQUENCIES = ("quarter", "month")


@dataclass(frozen=True)
class VatSettings:
    frequency: str = "quarter"  # 'quarter' | 'month'
    kor_from: date | None = None
    kor_until: date | None = None


def get_vat_settings(session: Session) -> VatSettings:
    row = session.get(VatSetting, 1)
    if row is None:
        return VatSettings()
    return VatSettings(row.frequency, row.kor_from, row.kor_until)


def kor_overlap(settings: VatSettings, start: date, end: date) -> str:
    """'none' | 'partial' | 'full': how much of [start, end] lies inside the KOR range."""
    if settings.kor_from is None:
        return "none"
    k_start = settings.kor_from
    k_end = settings.kor_until or date.max
    if k_start > end or k_end < start:
        return "none"
    return "full" if k_start <= start and end <= k_end else "partial"


def is_kor(period: VatPeriod, settings: VatSettings) -> str:
    """'none' | 'partial' | 'full'."""
    return kor_overlap(settings, *period_range(period))


def _kor_range(s: VatSettings) -> tuple[date, date] | None:
    return None if s.kor_from is None else (s.kor_from, s.kor_until or date.max)


def _subtract(a: tuple[date, date], b: tuple[date, date] | None) -> list[tuple[date, date]]:
    """The parts of interval a that are not in interval b."""
    if b is None or b[1] < a[0] or b[0] > a[1]:
        return [a]
    parts = []
    if a[0] < b[0]:
        parts.append((a[0], b[0] - timedelta(days=1)))
    if b[1] < a[1]:
        parts.append((b[1] + timedelta(days=1), a[1]))
    return parts


def _changed_intervals(old: VatSettings, new: VatSettings) -> list[tuple[date, date]]:
    a, b = _kor_range(old), _kor_range(new)
    return (_subtract(a, b) if a else []) + (_subtract(b, a) if b else [])


def _is_boundary(day: date, frequency: str) -> bool:
    if day.day != 1:
        return False
    return day.month in (1, 4, 7, 10) if frequency == "quarter" else True


def save_vat_settings(
    session: Session, frequency: str, kor_from: date | None, kor_until: date | None,
    today: date | None = None,
) -> VatSettings:
    today = today or date.today()
    if frequency not in FREQUENCIES:
        raise vat_error("VAT_FREQUENCY_INVALID")
    if kor_from is None and kor_until is not None:
        raise vat_error("VAT_KOR_START_INVALID", eenheid="kwartaal" if frequency == "quarter" else "maand")
    if kor_from is not None and not _is_boundary(kor_from, frequency):
        raise vat_error("VAT_KOR_START_INVALID", eenheid="kwartaal" if frequency == "quarter" else "maand")
    if kor_from is not None and kor_until is not None and kor_until < kor_from:
        raise vat_error("VAT_KOR_DATES")

    old = get_vat_settings(session)
    new = VatSettings(frequency, kor_from, kor_until)
    filed = list(session.scalars(select(VatReturn).order_by(VatReturn.start_date)))

    if frequency != old.frequency:
        for r in filed:
            if r.year >= today.year and r.kind != frequency:
                raise vat_error("VAT_FREQUENCY_CONFLICT", year=r.year)

    for lo, hi in _changed_intervals(old, new):
        for r in filed:
            if r.start_date <= hi and lo <= r.end_date:
                raise vat_error("VAT_KOR_FILED", periode=VatPeriod(r.year, r.kind, r.number).label)

    row = session.get(VatSetting, 1)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row is None:
        session.add(VatSetting(id=1, frequency=frequency, kor_from=kor_from, kor_until=kor_until, updated_at=now))
    else:
        row.frequency, row.kor_from, row.kor_until, row.updated_at = frequency, kor_from, kor_until, now
    session.flush()
    return new
