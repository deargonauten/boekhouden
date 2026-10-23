import pytest

from app.domain.sales.numbering import (
    NumberingConfig,
    NumberingError,
    format_number,
    get_config,
    next_number,
    peek_next_seq,
    save_config,
)


@pytest.fixture
def finalized_invoice(make_final, customer):
    return make_final(customer)


def test_default_is_year_dash_four_digits(session, year2026):
    assert get_config(session) == NumberingConfig("-", 4, False)
    assert next_number(session, 2026) == (1, "2026-0001")


def test_format_dot_three_digits():
    assert format_number(2026, 7, NumberingConfig(".", 3, True)) == "2026.007"
    assert format_number(2026, 1234, NumberingConfig(".", 3, True)) == "2026.1234"


def test_custom_start_continues_over_years(session, year2026):
    save_config(session, separator=".", digits=3, continuous=True, next_seq=42, year=2026)
    assert next_number(session, 2026) == (42, "2026.042")
    assert next_number(session, 2027) == (43, "2027.043")
    assert peek_next_seq(session, 2027) == 44


def test_per_year_series_restarts(session, year2026):
    save_config(session, separator="-", digits=4, continuous=False, next_seq=5, year=2026)
    assert next_number(session, 2026) == (5, "2026-0005")
    assert next_number(session, 2027) == (1, "2027-0001")


def test_switching_to_continuous_continues_after_highest_used(session, finalized_invoice):
    inv = finalized_invoice
    assert (inv.number_year, inv.number_seq) == (2026, 1)
    assert peek_next_seq(session, 2026) == 2
    save_config(session, separator=".", digits=3, continuous=True, next_seq=2, year=2026)
    assert next_number(session, 2027) == (2, "2027.002")


def test_next_number_must_be_above_used(session, finalized_invoice):
    with pytest.raises(NumberingError) as exc:
        save_config(session, separator=".", digits=3, continuous=True, next_seq=1, year=2026)
    assert "hoger zijn dan 1" in exc.value.message


@pytest.mark.parametrize("kw", [{"separator": "x"}, {"digits": 0}, {"digits": 9}])
def test_invalid_format_rejected(session, kw):
    args = dict(separator=".", digits=3, continuous=True, next_seq=1, year=2026) | kw
    with pytest.raises(NumberingError):
        save_config(session, **args)
