from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.vat.periods import VatPeriod
from app.domain.vat.settings import KOR_LIMIT_CENTS, VatSettings, get_vat_settings, is_kor, save_vat_settings
from tests.vat.vat_helpers import insert_return

TODAY = date(2026, 10, 23)


def fails(code, fn, *a, **kw):
    with pytest.raises(LedgerError) as e:
        fn(*a, **kw)
    assert e.value.code == code
    return e.value.message


def test_defaults_without_row(session):
    assert get_vat_settings(session) == VatSettings("quarter", None, None)


def test_save_and_read_back(session):
    save_vat_settings(session, "month", None, None, today=TODAY)
    assert get_vat_settings(session).frequency == "month"
    save_vat_settings(session, "quarter", None, None, today=TODAY)  # update of the single row
    assert get_vat_settings(session).frequency == "quarter"


def test_invalid_frequency(session):
    assert "kwartaal of per maand" in fails("VAT_FREQUENCY_INVALID", save_vat_settings, session, "week", None, None, TODAY)


@pytest.mark.parametrize("freq,start,ok", [
    ("quarter", date(2026, 7, 1), True),
    ("quarter", date(2026, 8, 1), False),
    ("quarter", date(2026, 7, 2), False),
    ("month", date(2026, 8, 1), True),
    ("month", date(2026, 8, 15), False),
])
def test_kor_start_on_period_boundary(session, freq, start, ok):
    if ok:
        assert save_vat_settings(session, freq, start, None, today=TODAY).kor_from == start
    else:
        fails("VAT_KOR_START_INVALID", save_vat_settings, session, freq, start, None, TODAY)


def test_kor_until_before_from(session):
    msg = fails("VAT_KOR_DATES", save_vat_settings, session, "quarter", date(2026, 7, 1), date(2026, 6, 30), TODAY)
    assert msg == "De einddatum van de KOR ligt vóór de startdatum."


def test_kor_until_without_from(session):
    fails("VAT_KOR_START_INVALID", save_vat_settings, session, "quarter", None, date(2026, 6, 30), TODAY)


def test_kor_until_equal_to_from_is_fine_and_past_dates_allowed(session):
    s = save_vat_settings(session, "month", date(2025, 1, 1), date(2025, 1, 31), today=TODAY)
    assert (s.kor_from, s.kor_until) == (date(2025, 1, 1), date(2025, 1, 31))


@pytest.mark.parametrize("period,kor_from,kor_until,expected", [
    (VatPeriod(2026, "quarter", 3), None, None, "none"),
    (VatPeriod(2026, "quarter", 3), date(2026, 7, 1), None, "full"),
    (VatPeriod(2026, "quarter", 3), date(2026, 1, 1), date(2026, 12, 31), "full"),
    (VatPeriod(2026, "quarter", 3), date(2026, 8, 1), None, "partial"),
    (VatPeriod(2026, "quarter", 3), date(2026, 1, 1), date(2026, 8, 31), "partial"),
    (VatPeriod(2026, "quarter", 3), date(2026, 10, 1), None, "none"),
    (VatPeriod(2026, "quarter", 3), date(2025, 1, 1), date(2026, 6, 30), "none"),
    (VatPeriod(2026, "month", 8), date(2026, 7, 1), date(2026, 9, 30), "full"),
])
def test_is_kor(period, kor_from, kor_until, expected):
    assert is_kor(period, VatSettings("quarter", kor_from, kor_until)) == expected


def test_frequency_change_refused_when_filed_in_current_year(session):
    insert_return(session, 2026, "quarter", 1)
    msg = fails("VAT_FREQUENCY_CONFLICT", save_vat_settings, session, "month", None, None, TODAY)
    assert msg == "Je kunt niet wisselen tussen kwartaal en maand in 2026: er is al een aangifte ingediend."


def test_frequency_change_allowed_when_filed_only_in_past_years_or_same_kind(session):
    insert_return(session, 2025, "quarter", 4)
    assert save_vat_settings(session, "month", None, None, today=TODAY).frequency == "month"
    insert_return(session, 2026, "month", 1)
    assert save_vat_settings(session, "month", None, None, today=TODAY).frequency == "month"


def test_kor_change_touching_filed_period_refused(session):
    insert_return(session, 2026, "quarter", 1)
    msg = fails("VAT_KOR_FILED", save_vat_settings, session, "quarter", date(2026, 1, 1), None, TODAY)
    assert "1e kwartaal 2026" in msg


def test_kor_change_after_filed_periods_allowed_and_unchanged_resave_ok(session):
    insert_return(session, 2026, "quarter", 1)
    save_vat_settings(session, "quarter", date(2026, 7, 1), None, today=TODAY)
    save_vat_settings(session, "quarter", date(2026, 7, 1), None, today=TODAY)  # unchanged
    save_vat_settings(session, "quarter", date(2026, 10, 1), None, today=TODAY)  # shrinks, touches Q3 only
    assert get_vat_settings(session).kor_from == date(2026, 10, 1)


def test_kor_start_moved_over_filed_period_refused(session):
    save_vat_settings(session, "quarter", date(2026, 1, 1), None, today=TODAY)
    insert_return(session, 2026, "quarter", 1)
    fails("VAT_KOR_FILED", save_vat_settings, session, "quarter", date(2026, 4, 1), None, TODAY)
    assert get_vat_settings(session).kor_from == date(2026, 1, 1)
    # ending the KOR after the filed period does not touch it
    save_vat_settings(session, "quarter", date(2026, 1, 1), date(2026, 6, 30), today=TODAY)


def test_kor_limit_is_information():
    assert KOR_LIMIT_CENTS == 2_000_000
