from datetime import date, timedelta

import pytest

from app.domain.checks import Check, CheckReport, run_checks
from app.domain.checks.types import OK_HEADLINE
from app.domain.vat.periods import VatPeriod
from tests.checks.conftest import Q3

START, END = date(2026, 7, 1), date(2026, 9, 30)
BEFORE, AFTER = START - timedelta(days=1), END + timedelta(days=1)
EXPENSE = [("4000", 1000, 0), ("1210", 0, 1000)]


def get(report, key) -> Check:
    return next(c for c in report.checks if c.key == key)


def test_keys_and_order(session, book):
    report = run_checks(session, Q3)
    assert [c.key for c in report.checks] == [
        "bank_ongeboekt", "onevenwichtig", "boeking_zonder_document", "inbox_ongeboekt", "concept_facturen",
    ]
    assert report.period == Q3


def test_empty_data_is_all_ok(session, book):
    report = run_checks(session, Q3)
    assert all(c.level == "ok" and c.count == 0 and c.items == () for c in report.checks)
    assert report.verdict == "ok"
    assert report.problem_count == 0
    assert report.headline == OK_HEADLINE
    assert get(report, "bank_ongeboekt").amount_cents == 0


# --- bank_ongeboekt -----------------------------------------------------------


def test_bank_counts_new_in_period_with_abs_sum(session, book, make_txn):
    make_txn(-12100)
    make_txn(5000, day=START)
    make_txn(-250, day=END)
    c = get(run_checks(session, Q3), "bank_ongeboekt")
    assert (c.level, c.count, c.amount_cents) == ("fout", 3, 17350)
    assert len(c.items) == 3
    assert c.fix_href == "/bank/afletteren"
    assert "3 bankmutaties" in c.explanation and "Verwerk ze eerst" in c.explanation


def test_bank_ignores_outside_period_and_other_status(session, book, make_txn):
    make_txn(-100, day=BEFORE)
    make_txn(-100, day=AFTER)
    make_txn(-100, status="genegeerd")
    make_txn(-100, status="geboekt")
    c = get(run_checks(session, Q3), "bank_ongeboekt")
    assert (c.level, c.count, c.amount_cents) == ("ok", 0, 0)


def test_bank_items_capped_at_five(session, book, make_txn):
    for _ in range(7):
        make_txn(-100)
    c = get(run_checks(session, Q3), "bank_ongeboekt")
    assert c.count == 7 and len(c.items) == 5
    assert c.amount_cents == 700
    assert "€ 1,00" in c.items[0].label


def test_bank_single_is_singular(session, book, make_txn):
    make_txn(-100)
    c = get(run_checks(session, Q3), "bank_ongeboekt")
    assert "1 bankmutatie " in c.explanation


# --- onevenwichtig --------------------------------------------------------------


def test_unbalanced_entry_names_the_difference(session, book, raw_entry):
    e = raw_entry([("4000", 1210, 0)])
    c = get(run_checks(session, Q3), "onevenwichtig")
    assert (c.level, c.count) == ("fout", 1)
    assert c.items[0].href == f"/boeken/{e.id}"
    assert "Debet en credit zijn niet gelijk: er ontbreekt €12,10" in c.items[0].label
    assert c.fix_href == "/boeken"


def test_unbalanced_difference_is_absolute(session, book, raw_entry):
    raw_entry([("4000", 1210, 0), ("1210", 0, 10)])
    c = get(run_checks(session, Q3), "onevenwichtig")
    assert "ontbreekt €12,00" in c.items[0].label


def test_entry_without_lines_is_reported(session, book, raw_entry):
    e = raw_entry([])
    c = get(run_checks(session, Q3), "onevenwichtig")
    assert c.count == 1 and c.items[0].href == f"/boeken/{e.id}"
    assert "geen regels" in c.items[0].label


def test_balanced_and_outside_are_not_reported(session, book, raw_entry):
    raw_entry([("4000", 500, 0), ("1210", 0, 500)])
    raw_entry([("4000", 500, 0)], day=BEFORE)
    raw_entry([("4000", 500, 0)], day=AFTER)
    assert get(run_checks(session, Q3), "onevenwichtig").level == "ok"


# --- boeking_zonder_document -----------------------------------------------------


def test_manual_expense_without_document_is_reported(session, book, manual):
    e = manual(EXPENSE, desc="Pennen")
    c = get(run_checks(session, Q3), "boeking_zonder_document")
    assert (c.level, c.count) == ("let_op", 1)
    assert c.items[0].href == f"/boeken/{e.id}"
    assert "Pennen" in c.items[0].label and "€ 10,00" in c.items[0].label
    # No supported way to attach a document to an existing booking: no fix button, no inbox advice.
    assert c.fix_href == "" and c.fix_label == ""
    assert "inbox" not in c.explanation.lower()
    assert "niet nog een keer" in c.explanation


def test_manual_revenue_without_document_is_reported(session, book, manual):
    manual([("1210", 1000, 0), ("8000", 0, 1000)])
    assert get(run_checks(session, Q3), "boeking_zonder_document").count == 1


def test_linked_document_excludes(session, book, manual, make_doc):
    e = manual(EXPENSE)
    make_doc(status="geboekt", entry_id=e.id)
    assert get(run_checks(session, Q3), "boeking_zonder_document").level == "ok"


def test_without_expense_or_revenue_line_is_ignored(session, book, manual):
    manual([("1100", 1000, 0), ("1210", 0, 1000)])
    assert get(run_checks(session, Q3), "boeking_zonder_document").level == "ok"


def test_memoriaal_journal_is_ignored(session, book):
    book.post(EXPENSE, journal="MEM")
    assert get(run_checks(session, Q3), "boeking_zonder_document").level == "ok"


def test_storno_and_reversed_entry_are_ignored(session, book, manual):
    e = manual(EXPENSE)
    book.reverse(e)
    assert get(run_checks(session, Q3), "boeking_zonder_document").level == "ok"


def test_source_typed_entries_are_ignored(session, book, raw_entry):
    for st in ("verkoopfactuur", "inkoopfactuur", "beginbalans"):
        raw_entry([("4000", 1000, 0), ("1210", 0, 1000)], journal="BANK", source_type=st)
    assert get(run_checks(session, Q3), "boeking_zonder_document").level == "ok"


def test_outside_period_ignored(session, book, manual):
    manual(EXPENSE, day=BEFORE)
    manual(EXPENSE, day=AFTER)
    assert get(run_checks(session, Q3), "boeking_zonder_document").level == "ok"


# --- inbox_ongeboekt --------------------------------------------------------------


def test_inbox_counts_nieuw_and_herkend_up_to_period_end(session, book, make_doc):
    make_doc("nieuw")
    make_doc("herkend", received=date(2025, 1, 5))  # any age
    make_doc("nieuw", received=END)  # last day counts
    c = get(run_checks(session, Q3), "inbox_ongeboekt")
    assert (c.level, c.count, c.fix_href) == ("let_op", 3, "/inbox")
    assert "kan invloed hebben op je btw" in c.explanation
    assert all(i.href.startswith("/inbox/") for i in c.items)


def test_inbox_ignores_booked_and_later(session, book, manual, make_doc):
    e = manual(EXPENSE)
    make_doc("geboekt", entry_id=e.id)
    make_doc("nieuw", received=AFTER)
    assert get(run_checks(session, Q3), "inbox_ongeboekt").level == "ok"


# --- concept_facturen -------------------------------------------------------------


def test_concepts_up_to_end(session, book, make_invoice, raw_entry):
    a = make_invoice("concept")
    make_invoice("concept", day=END)
    make_invoice("concept", day=AFTER)
    e = raw_entry([("4000", 1000, 0), ("1210", 0, 1000)], source_type="verkoopfactuur")
    make_invoice("definitief", entry_id=e.id)
    c = get(run_checks(session, Q3), "concept_facturen")
    assert (c.level, c.count, c.fix_href) == ("let_op", 2, "/verkoop")
    assert f"/verkoop/{a.id}" in {i.href for i in c.items}
    assert "telt nog niet mee in je btw" in c.explanation
    assert "Jansen Installatie" in c.items[0].label


def test_old_concept_counts(session, book, make_invoice):
    make_invoice("concept", day=date(2025, 12, 1))
    assert get(run_checks(session, Q3), "concept_facturen").count == 1


# --- verdict ----------------------------------------------------------------------


def test_verdict_let_op(session, book, make_doc):
    make_doc("nieuw")
    r = run_checks(session, Q3)
    assert (r.verdict, r.problem_count, r.headline) == ("let_op", 1, "1 ding om te controleren")


def test_verdict_fout_wins_and_headline_counts(session, book, make_doc, make_txn, make_invoice):
    make_doc("nieuw")
    make_invoice()
    make_txn()
    r = run_checks(session, Q3)
    assert (r.verdict, r.problem_count, r.headline) == ("fout", 3, "3 dingen om te controleren")


def test_report_is_frozen_and_writes_nothing(session, book, make_txn):
    make_txn()
    session.flush()
    r = run_checks(session, Q3)
    assert isinstance(r, CheckReport)
    with pytest.raises(Exception):
        r.checks = ()
    assert not session.dirty and not session.new


def test_month_period(session, book, make_txn):
    make_txn(day=date(2026, 8, 3))
    assert get(run_checks(session, VatPeriod(2026, "month", 8)), "bank_ongeboekt").count == 1
    assert get(run_checks(session, VatPeriod(2026, "month", 7)), "bank_ongeboekt").count == 0


def test_today_param_is_accepted(session, book):
    assert run_checks(session, Q3, today=date(2026, 10, 1)).verdict == "ok"
