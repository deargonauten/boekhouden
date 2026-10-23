from datetime import date

import pytest

from app.domain.vat.report import PAY, REFUND, ZERO, build_vat_report, drilldown, round_whole_cents
from app.models import VatCode
from tests.vat.vat_helpers import DAY, Q3, Book, codes, rubriek

TODAY = date(2026, 10, 23)


@pytest.fixture
def book(session):
    return Book(session)


def report(session, **kw):
    return build_vat_report(session, *Q3, **kw)


# --- rounding ------------------------------------------------------------------


@pytest.mark.parametrize("cents,whole", [
    (123499, 123400), (99, 0), (100, 100), (0, 0),
    (-123499, -123400), (-99, 0), (-100, -100), (-101, -100),
])
def test_round_whole_euros_toward_zero_never_negative_zero(cents, whole):
    result = round_whole_cents(cents)
    assert result == whole
    assert str(result) != "-0"


# --- aggregation per rubriek -----------------------------------------------------


def test_nl_21_sale(session, book):
    book.sale(100000, 21000)
    r = report(session)
    line = rubriek(r, "1a")
    assert (line.grondslag_cents, line.grondslag_whole_cents, line.vat_cents) == (100000, 100000, 21000)
    assert r.totals == {"5a": 21000, "5b": 0, "5c": 21000, "5g": 21000}
    assert r.direction == PAY
    assert not r.warnings


def test_nl_9_sale(session, book):
    book.sale(10000, 900, code="NL_9", revenue="8010", btw="3110")
    r = report(session)
    assert (rubriek(r, "1b").grondslag_cents, rubriek(r, "1b").vat_cents) == (10000, 900)
    assert r.totals["5g"] == 900


def test_rubriek_order_and_labels_follow_the_form(session, book):
    r = report(session)
    assert [l.rubriek for l in r.lines] == ["1a", "1b", "1c", "1d", "1e", "2a", "3a", "3b", "3c", "4a", "4b"]
    assert rubriek(r, "1a").label == "Omzet met 21% btw"
    assert rubriek(r, "2a").side == "purchase"
    assert rubriek(r, "3b").side == "sales"


def test_whole_euro_rounding_in_report(session, book):
    book.sale(123499, 25935)
    line = rubriek(report(session), "1a")
    assert line.grondslag_cents == 123499
    assert line.grondslag_whole_cents == 123400
    assert line.vat_cents == 25935


def test_credit_note_is_negative(session, book):
    book.sale(100000, 21000)
    book.credit_note(10000, 2100)
    line = rubriek(report(session), "1a")
    assert (line.grondslag_cents, line.vat_cents) == (90000, 18900)


def test_credit_note_larger_than_sales_gives_negative_whole_euros(session, book):
    book.credit_note(12345, 2592)
    r = report(session)
    assert rubriek(r, "1a").grondslag_cents == -12345
    assert rubriek(r, "1a").grondslag_whole_cents == -12300
    assert r.totals["5g"] == -2592
    assert r.direction == REFUND


def test_storno_nets_out(session, book):
    e = book.sale(100000, 21000)
    book.reverse(e)
    r = report(session)
    assert rubriek(r, "1a").grondslag_cents == 0
    assert r.totals["5g"] == 0
    assert r.direction == ZERO
    assert r.is_empty


def test_purchase_nl_21_gives_voorbelasting_only(session, book):
    book.purchase(10000, 2100)
    r = report(session)
    assert r.totals == {"5a": 0, "5b": 2100, "5c": -2100, "5g": -2100}
    assert r.direction == REFUND
    assert not r.warnings
    assert all(l.grondslag_cents == 0 for l in r.lines)


def test_verlegd_purchase_2a_counts_in_5a_and_5b(session, book):
    book.post([
        ("4000", 10000, 0, "VERLEGD"), ("1410", 2100, 0), ("3130", 0, 2100), ("2000", 0, 10000),
    ])
    r = report(session)
    assert (rubriek(r, "2a").grondslag_cents, rubriek(r, "2a").vat_cents) == (10000, 2100)
    assert r.totals == {"5a": 2100, "5b": 2100, "5c": 0, "5g": 0}
    assert r.direction == ZERO
    assert not r.warnings


def test_eu_goederen_sale_3b_has_no_btw(session, book):
    book.sale(50000, 0, code="EU_GOEDEREN", revenue="8040")
    r = report(session)
    assert (rubriek(r, "3b").grondslag_cents, rubriek(r, "3b").vat_cents) == (50000, 0)
    assert r.totals["5g"] == 0
    assert "W1" not in codes(r)


def test_eu_diensten_sale_3b(session, book):
    book.sale(50000, 0, code="EU_DIENSTEN", revenue="8040")
    assert rubriek(report(session), "3b").grondslag_cents == 50000


def test_eu_purchase_4b(session, book):
    book.post([("4000", 10000, 0, "EU_GOEDEREN"), ("1410", 2100, 0), ("3130", 0, 2100), ("2000", 0, 10000)])
    r = report(session)
    assert (rubriek(r, "4b").grondslag_cents, rubriek(r, "4b").vat_cents) == (10000, 2100)
    assert r.totals["5g"] == 0


def test_export_sale_3a_and_purchase_4a(session, book):
    book.sale(70000, 0, code="EXPORT", revenue="8050")
    book.post([("4000", 10000, 0, "EXPORT"), ("1410", 2100, 0), ("3130", 0, 2100), ("2000", 0, 10000)])
    r = report(session)
    assert rubriek(r, "3a").grondslag_cents == 70000 and rubriek(r, "3a").vat_cents == 0
    assert rubriek(r, "4a").grondslag_cents == 10000 and rubriek(r, "4a").vat_cents == 2100


def test_zero_percent_sale_goes_to_1e_and_geen_is_ignored(session, book):
    book.sale(20000, 0, code="NL_0", revenue="8020")
    book.sale(30000, 0, code="GEEN", revenue="8000")
    book.purchase(5000, 0, code="NL_0")
    r = report(session)
    assert rubriek(r, "1e").grondslag_cents == 20000
    assert sum(l.grondslag_cents for l in r.lines) == 20000


def test_verlegd_sale_on_revenue_account_is_1e(session, book):
    book.sale(20000, 0, code="VERLEGD", revenue="8030")
    r = report(session)
    assert rubriek(r, "1e").grondslag_cents == 20000
    assert rubriek(r, "2a").grondslag_cents == 0


def test_privegebruik_1d_from_3140(session, book):
    book.post([("2000", 1210, 0), ("3140", 0, 1210)])
    r = report(session)
    assert rubriek(r, "1d").vat_cents == 1210
    assert r.totals["5a"] == 1210


def test_btw_1c_other_rate(session, book):
    session.add(VatCode(code="NL_6", name="6%", rate_bp=600, is_active=True, is_system=False,
                        sales_rubriek="1c", purchase_rubriek="5b"))
    session.flush()
    book.sale(10000, 600, code="NL_6", revenue="8000", btw="3120")
    r = report(session)
    assert (rubriek(r, "1c").grondslag_cents, rubriek(r, "1c").vat_cents) == (10000, 600)


def test_opening_entries_excluded(session, book):
    book.post([("1210", 12100, 0), ("8000", 0, 10000, "NL_21"), ("3100", 0, 2100)], kind="opening")
    r = report(session)
    assert r.is_empty and r.totals["5g"] == 0


def test_date_range_is_inclusive_and_ignores_outside(session, book):
    book.sale(10000, 2100, day=date(2026, 7, 1))
    book.sale(10000, 2100, day=date(2026, 9, 30))
    book.sale(10000, 2100, day=date(2026, 6, 30))
    book.sale(10000, 2100, day=date(2026, 10, 1))
    assert rubriek(report(session), "1a").grondslag_cents == 20000


def test_nihil_report(session, book):
    r = report(session)
    assert r.is_empty
    assert r.message == "Geen btw in deze periode"
    assert r.totals == {"5a": 0, "5b": 0, "5c": 0, "5g": 0}
    assert r.direction == ZERO
    assert r.warnings == []


def test_direction_labels(session, book):
    assert report(session).direction_label == "Niets te betalen"
    book.sale(10000, 2100)
    r = report(session)
    assert r.direction_label == "Te betalen" and r.message is None


def test_multiple_verlegd_kinds_in_one_entry_goes_to_largest(session, book):
    e = book.post([
        ("4000", 10000, 0, "VERLEGD"), ("4000", 4000, 0, "EU_GOEDEREN"),
        ("1410", 2940, 0), ("3130", 0, 2940), ("2000", 0, 14000),
    ])
    r = report(session)
    assert rubriek(r, "2a").vat_cents == 2940
    assert rubriek(r, "4b").vat_cents == 0
    w = next(w for w in r.warnings if w.code == "W_MULTI_VERLEGD")
    assert w.entry_ids == (e.id,)
    assert "meerdere verlegde soorten" in w.message


def test_ambiguous_line_is_warned_not_guessed(session, book):
    # EU_GOEDEREN has both a sales and a purchase rubriek; equity account is neither side.
    e = book.post([("1210", 10000, 0), ("2000", 0, 10000, "EU_GOEDEREN")])
    r = report(session)
    assert all(l.grondslag_cents == 0 for l in r.lines)
    assert [w.entry_ids for w in r.warnings if w.code == "AMBIGUOUS_LINE"] == [(e.id,)]


# --- warnings --------------------------------------------------------------------


def test_normal_entries_give_no_warnings(session, book):
    book.sale(10000, 2100)
    book.purchase(10000, 2100)
    assert report(session).warnings == []


def test_w1_grondslag_without_btw_line(session, book):
    e = book.sale(10000, 0)  # NL_21 code but no btw line
    w = [w for w in report(session).warnings if w.code == "W1"]
    assert len(w) == 1 and w[0].entry_ids == (e.id,)
    assert "btw-grondslag zonder bijbehorende btw-boeking" in w[0].message


def test_w1_purchase_without_voorbelasting(session, book):
    e = book.purchase(10000, 0)
    assert [w.entry_ids for w in report(session).warnings if w.code == "W1"] == [(e.id,)]


def test_w1_negative_zero_percent_code_has_no_btw_line(session, book):
    book.sale(10000, 0, code="NL_0", revenue="8020")
    assert "W1" not in codes(report(session))


def test_w2_btw_line_without_grondslag(session, book):
    e = book.post([("1210", 2100, 0), ("3100", 0, 2100)])
    w = [w for w in report(session).warnings if w.code == "W2"]
    assert [x.entry_ids for x in w] == [(e.id,)]


def test_w3_amount_deviates_from_rate(session, book):
    e = book.sale(10000, 2000)  # should be 2100
    w = [w for w in report(session).warnings if w.code == "W3"]
    assert [x.entry_ids for x in w] == [(e.id,)]


def test_w3_up_to_five_cents_is_allowed(session, book):
    book.sale(10001, 2105)  # 21% of 100,01 = 21,0021; diff 0,03
    book.sale(10000, 2105)  # diff exactly 0,05
    assert "W3" not in codes(report(session))
    book.sale(10000, 2106)
    assert "W3" in codes(report(session))


def test_w3_purchase_voorbelasting_deviation(session, book):
    book.purchase(10000, 1000)
    assert "W3" in codes(report(session))


def test_w4_eu_sale_without_klant(session, book):
    e = book.sale(50000, 0, code="EU_GOEDEREN", revenue="8040")
    w = [w for w in report(session).warnings if w.code == "W4"]
    assert [x.entry_ids for x in w] == [(e.id,)]
    assert "ICP" in w[0].message


def test_w5_verlegd_without_matching_3130_and_1410(session, book):
    e = book.post([("4000", 10000, 0, "VERLEGD"), ("2000", 0, 10000)])
    assert [w.entry_ids for w in report(session).warnings if w.code == "W5"] == [(e.id,)]


def test_w5_unequal_amounts(session, book):
    book.post([("4000", 10000, 0, "VERLEGD"), ("1410", 2100, 0), ("3130", 0, 2000), ("2000", 0, 10100)])
    assert "W5" in codes(report(session))


def test_w5_negative_when_balanced(session, book):
    book.post([("4000", 10000, 0, "VERLEGD"), ("1410", 2100, 0), ("3130", 0, 2100), ("2000", 0, 10000)])
    assert "W5" not in codes(report(session))


def test_w6_earlier_period_has_entries_but_not_filed(session, book):
    book.sale(10000, 2100, day=date(2026, 2, 10))
    r = build_vat_report(session, date(2026, 4, 1), date(2026, 6, 30))
    w = [w for w in r.warnings if w.code == "W6"]
    assert len(w) == 1 and "1e kwartaal 2026" in w[0].message


def test_w6_not_for_first_period_or_empty_earlier(session, book):
    book.sale(10000, 2100, day=date(2026, 5, 10))
    assert "W6" not in codes(build_vat_report(session, date(2026, 1, 1), date(2026, 3, 31)))
    assert "W6" not in codes(build_vat_report(session, date(2026, 4, 1), date(2026, 6, 30)))


def test_w7_inactive_vat_code(session, book):
    e = book.sale(10000, 2100)
    session.get(VatCode, "NL_21").is_active = False
    session.flush()
    assert [w.entry_ids for w in report(session).warnings if w.code == "W7"] == [(e.id,)]


def test_w8_kor_with_btw_lines(session, book):
    from app.domain.vat.settings import save_vat_settings

    save_vat_settings(session, "quarter", date(2026, 7, 1), None)
    book.sale(10000, 2100)
    r = report(session)
    assert "W8" in codes(r)
    assert "Je gebruikt de KOR maar" in next(w for w in r.warnings if w.code == "W8").message


def test_w8_not_without_kor_and_partial_kor_has_own_warning(session, book):
    from app.domain.vat.settings import save_vat_settings

    book.sale(10000, 2100)
    assert "W8" not in codes(report(session))
    save_vat_settings(session, "month", date(2026, 8, 1), None)
    r = report(session)
    assert "KOR_PARTIAL" in codes(r) and "W8" not in codes(r)


# --- drill-down ------------------------------------------------------------------


def test_drilldown_lists_grondslag_and_btw_lines(session, book):
    e = book.sale(100000, 21000)
    book.sale(5000, 900, code="NL_9", revenue="8010", btw="3110")
    rows = drilldown(session, *Q3, "1a")
    assert {(r.entry_id, r.account_code, r.kind, r.amount_cents) for r in rows} == {
        (e.id, "8000", "grondslag", 100000), (e.id, "3100", "btw", 21000),
    }


def test_drilldown_5b_and_2a(session, book):
    p = book.purchase(10000, 2100)
    v = book.post([("4000", 10000, 0, "VERLEGD"), ("1410", 2100, 0), ("3130", 0, 2100), ("2000", 0, 10000)])
    assert {(r.entry_id, r.account_code) for r in drilldown(session, *Q3, "5b")} == {
        (p.id, "1400"), (v.id, "1410"),
    }
    assert {(r.account_code, r.kind) for r in drilldown(session, *Q3, "2a")} == {
        ("4000", "grondslag"), ("3130", "btw"),
    }


def test_drilldown_unknown_rubriek_is_empty(session, book):
    assert drilldown(session, *Q3, "9z") == []


def test_w3_compensating_errors_in_different_boxes(session, book):
    # 21% sale with 9 on 3100 (should be 21) and 9% sale with 21 on 3110 (should be 9)
    e = book.post([
        ("1210", 20000 + 3000, 0), ("8000", 0, 10000, "NL_21"), ("8000", 0, 10000, "NL_9"),
        ("3100", 0, 900), ("3110", 0, 2100),
    ], journal="VK")
    w = [w for w in report(session).warnings if w.code == "W3"]
    assert [x.entry_ids for x in w] == [(e.id,)]
