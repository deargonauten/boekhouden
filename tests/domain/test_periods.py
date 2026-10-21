from datetime import date

import pytest

from app.domain.ledger.periods import generate_periods, period_for_date


def test_twelve_periods_2025():
    ps = generate_periods(2025)
    assert [p.number for p in ps] == list(range(1, 13))
    assert ps[0].start_date == date(2025, 1, 1)
    assert ps[0].end_date == date(2025, 1, 31)
    assert ps[1].end_date == date(2025, 2, 28)
    assert ps[11].end_date == date(2025, 12, 31)


def test_leap_year_2024():
    assert generate_periods(2024)[1].end_date == date(2024, 2, 29)


def test_century_rules():
    assert generate_periods(1900)[1].end_date == date(1900, 2, 28)
    assert generate_periods(2000)[1].end_date == date(2000, 2, 29)


def test_contiguous_and_complete():
    ps = generate_periods(2025)
    for a, b in zip(ps, ps[1:]):
        assert (b.start_date - a.end_date).days == 1


@pytest.mark.parametrize("bad", [True, 2025.0, "2025", 0, 10000])
def test_bad_year(bad):
    with pytest.raises((TypeError, ValueError)):
        generate_periods(bad)


def test_period_for_date():
    ps = generate_periods(2024)
    assert period_for_date(ps, date(2024, 2, 29)).number == 2
    assert period_for_date(ps, date(2024, 1, 1)).number == 1
    assert period_for_date(ps, date(2024, 12, 31)).number == 12
    assert period_for_date(ps, date(2025, 1, 1)) is None
    assert period_for_date(ps, date(2023, 12, 31)) is None
