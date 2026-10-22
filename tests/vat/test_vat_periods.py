from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.vat.periods import (
    VatPeriod, deadline, is_overdue, months, overlaps, period_for_date, period_range,
    periods_of_year, previous, quarter_of,
)


@pytest.mark.parametrize("n,start,end", [
    (1, date(2026, 1, 1), date(2026, 3, 31)),
    (2, date(2026, 4, 1), date(2026, 6, 30)),
    (3, date(2026, 7, 1), date(2026, 9, 30)),
    (4, date(2026, 10, 1), date(2026, 12, 31)),
])
def test_quarter_ranges(n, start, end):
    assert period_range(VatPeriod(2026, "quarter", n)) == (start, end)


def test_month_range_leap_february():
    assert period_range(VatPeriod(2024, "month", 2)) == (date(2024, 2, 1), date(2024, 2, 29))
    assert period_range(VatPeriod(2025, "month", 2)) == (date(2025, 2, 1), date(2025, 2, 28))


def test_months_of_period():
    assert months(VatPeriod(2026, "quarter", 3)) == [7, 8, 9]
    assert months(VatPeriod(2026, "month", 5)) == [5]


@pytest.mark.parametrize("p,expected", [
    (VatPeriod(2026, "quarter", 1), date(2026, 4, 30)),
    (VatPeriod(2026, "quarter", 4), date(2027, 1, 31)),
    (VatPeriod(2026, "month", 1), date(2026, 2, 28)),
    (VatPeriod(2026, "month", 12), date(2027, 1, 31)),
    (VatPeriod(2024, "month", 1), date(2024, 2, 29)),
])
def test_deadline(p, expected):
    assert deadline(p) == expected


def test_overdue_relative_to_injected_today():
    p = VatPeriod(2026, "quarter", 1)
    assert not is_overdue(p, date(2026, 4, 30))
    assert is_overdue(p, date(2026, 5, 1))


@pytest.mark.parametrize("args", [
    (2026, "quarter", 0), (2026, "quarter", 5), (2026, "month", 13), (2026, "month", 0),
    (2026, "week", 1), (0, "quarter", 1), (2026, "quarter", True),
])
def test_invalid_period_raises_plain_dutch(args):
    with pytest.raises(LedgerError) as e:
        VatPeriod(*args)
    assert e.value.code == "VAT_PERIOD_INVALID"
    assert "kwartaal van 1 tot 4" in e.value.message


def test_labels_and_slug():
    assert VatPeriod(2026, "quarter", 3).label == "3e kwartaal 2026"
    assert VatPeriod(2026, "month", 7).label == "juli 2026"
    assert VatPeriod(2026, "quarter", 3).slug == "2026-Q3"
    assert VatPeriod(2026, "month", 7).slug == "2026-M07"


def test_helpers():
    assert quarter_of(date(2026, 6, 30)) == 2
    assert [p.number for p in periods_of_year(2026, "quarter")] == [1, 2, 3, 4]
    assert len(periods_of_year(2026, "month")) == 12
    assert period_for_date(date(2026, 8, 3), "quarter") == VatPeriod(2026, "quarter", 3)
    assert period_for_date(date(2026, 8, 3), "month") == VatPeriod(2026, "month", 8)
    assert previous(VatPeriod(2026, "quarter", 1)) is None
    assert previous(VatPeriod(2026, "quarter", 3)) == VatPeriod(2026, "quarter", 2)
    assert overlaps(VatPeriod(2026, "quarter", 1), VatPeriod(2026, "month", 3))
    assert not overlaps(VatPeriod(2026, "quarter", 1), VatPeriod(2026, "month", 4))
