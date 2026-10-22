from datetime import date, timedelta

import pytest

from app.domain.sales.amounts import (
    ageing_bucket,
    compute_totals,
    due_date,
    line_excl,
    parse_price,
    parse_quantity,
)
from app.domain.sales.errors import SalesError
from app.domain.sales.types import LineInput

RATES = {"NL_21": 2100, "NL_9": 900, "NL_0": 0}


def L(qty, price, code="NL_21", account=1):
    return LineInput(
        description="x", quantity_milli=qty, unit_price_cents=price, vat_code=code, account_id=account
    )


def test_line_excl_exact_and_half_up():
    assert line_excl(1000, 1250) == 1250
    assert line_excl(1500, 1000) == 1500  # 1,5 x 10,00
    assert line_excl(333, 100) == 33  # 33.3 -> 33
    assert line_excl(335, 100) == 34  # 33.5 -> 34 (half up)
    assert line_excl(1, 1) == 0  # 0.001
    assert line_excl(500, 1) == 1  # 0.5 -> 1
    assert line_excl(2500, 1999) == 4998  # 4997.5 -> 4998


def test_vat_rounded_per_rate_group_not_per_line():
    t = compute_totals([L(1000, 10)] * 3, RATES)
    assert t.total_excl_cents == 30
    assert t.groups[0].vat_cents == 6  # 30 * 21% = 6.3
    assert t.total_incl_cents == 36
    # per line 50 * 21% = 10.5 -> 11 (33 in total); per group 150 * 21% = 31.5 -> 32
    t = compute_totals([L(1000, 50)] * 3, RATES)
    assert t.groups[0].base_cents == 150
    assert t.groups[0].vat_cents == 32


def test_mixed_rates_and_totals():
    t = compute_totals([L(1000, 10000, "NL_21"), L(2000, 5000, "NL_9"), L(1000, 2500, "NL_0")], RATES)
    by = {g.vat_code: g for g in t.groups}
    assert (by["NL_21"].base_cents, by["NL_21"].vat_cents) == (10000, 2100)
    assert (by["NL_9"].base_cents, by["NL_9"].vat_cents) == (10000, 900)
    assert (by["NL_0"].base_cents, by["NL_0"].vat_cents) == (2500, 0)
    assert t.total_excl_cents == 22500
    assert t.total_vat_cents == 3000
    assert t.total_incl_cents == 25500
    assert t.line_excl_cents == (10000, 10000, 2500)


def test_groups_sorted_by_rate_descending_and_unknown_code_refused():
    t = compute_totals([L(1000, 100, "NL_0"), L(1000, 100, "NL_21")], RATES)
    assert [g.vat_code for g in t.groups] == ["NL_21", "NL_0"]
    with pytest.raises(SalesError):
        compute_totals([L(1000, 100, "XX")], RATES)


def test_due_date():
    assert due_date(date(2026, 1, 31), 30) == date(2026, 3, 2)
    assert due_date(date(2026, 1, 31), 0) == date(2026, 1, 31)


@pytest.mark.parametrize(
    "text,expected",
    [("1", 1000), ("1,5", 1500), ("1.5", 1500), ("0,001", 1), ("12,250", 12250), (" 2 ", 2000)],
)
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "0", "-1", "1,2345", "1,2,3"])
def test_parse_quantity_refuses(text):
    with pytest.raises(SalesError):
        parse_quantity(text)


@pytest.mark.parametrize(
    "text,expected",
    [("12,50", 1250), ("12.50", 1250), ("1.234,56", 123456), ("12", 1200), ("0", 0), ("€ 9,5", 950), ("12.5", 1250)],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["", "-1,00", "abc", "1,234"])
def test_parse_price_refuses(text):
    with pytest.raises(SalesError):
        parse_price(text)


@pytest.mark.parametrize(
    "days_overdue,bucket",
    [(-5, "not_due"), (0, "not_due"), (1, "d1_30"), (30, "d1_30"), (31, "d31_60"), (60, "d31_60"),
     (61, "d61_90"), (90, "d61_90"), (91, "over_90")],
)
def test_ageing_bucket_boundaries(days_overdue, bucket):
    today = date(2026, 6, 30)
    assert ageing_bucket(today - timedelta(days=days_overdue), today) == bucket
