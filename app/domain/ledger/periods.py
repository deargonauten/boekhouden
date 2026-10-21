"""Pure period generation: a boekjaar is a calendar year of 12 monthly periods."""

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PeriodSpec:
    number: int
    start_date: date
    end_date: date


def generate_periods(year: int) -> list[PeriodSpec]:
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("Jaar moet een geheel getal zijn")
    if not 1 <= year <= 9999:
        raise ValueError(f"Ongeldig jaar: {year}")
    return [
        PeriodSpec(
            number=month,
            start_date=date(year, month, 1),
            end_date=date(year, month, calendar.monthrange(year, month)[1]),
        )
        for month in range(1, 13)
    ]


def period_for_date(periods: list[PeriodSpec], day: date) -> PeriodSpec | None:
    for period in periods:
        if period.start_date <= day <= period.end_date:
            return period
    return None
