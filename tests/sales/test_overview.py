from datetime import date

from app.domain.opening import OpeningInput, OpeningItemInput, book_opening_balance
from app.domain.sales import (
    LineInput,
    create_credit_concept,
    debiteuren_overview,
    debtor_open_items,
    debtor_totals,
    derive_status,
    finalize,
    list_documents,
    stats,
)
from app.domain.sales.service import open_cents_of

TODAY = date(2026, 6, 30)


def one_line(cents):
    return [LineInput("Werk", 1000, cents, "NL_0", None)]  # 0%: total = price


def derive(**kw):
    base = dict(kind="invoice", status="definitief", total_cents=1000, paid_cents=0, applied_cents=0,
                due_date=date(2026, 7, 10), today=TODAY, reversed=False)
    base.update(kw)
    return derive_status(**base)


def test_derive_status_all_states():
    assert derive(status="concept") == "concept"
    assert derive() == "openstaand"
    assert derive(due_date=date(2026, 6, 29)) == "te_laat"
    assert derive(due_date=date(2026, 6, 30)) == "openstaand"  # due today is not late yet
    assert derive(paid_cents=400) == "deels_betaald"
    assert derive(paid_cents=1000) == "betaald"
    assert derive(applied_cents=1000) == "gecrediteerd"
    assert derive(paid_cents=400, applied_cents=600) == "betaald"
    assert derive(reversed=True, paid_cents=1000) == "gestorneerd"
    assert derive(kind="credit_note", applied_cents=1000) == "verrekend"
    assert derive(kind="credit_note", due_date=date(2020, 1, 1)) == "openstaand"  # never te laat
    assert open_cents_of("invoice", 1000, 1500, 0) == 0


def test_ageing_overview_buckets_and_totals(session, make_final, make_customer, make_concept):
    a, b = make_customer("Alfa"), make_customer("Beta")
    # due dates = invoice date + 30 days; today 2026-06-30
    make_final(b, day=date(2026, 1, 15), lines=one_line(40000))  # due 02-14: 136 days -> >90
    make_final(b, day=date(2026, 3, 30), lines=one_line(30000))  # due 04-29: 62 days late -> 61-90
    make_final(a, day=date(2026, 5, 1), lines=one_line(20000))  # due 05-31: 30 days late -> 1-30
    make_final(a, day=date(2026, 6, 20), lines=one_line(10000))  # due 07-20: not due
    make_concept(b, lines=one_line(99900))  # concept never counts
    rows = {r.contact_name: r for r in debiteuren_overview(session, TODAY)}
    assert (rows["Alfa"].not_due_cents, rows["Alfa"].d1_30_cents, rows["Alfa"].total_cents) == (10000, 20000, 30000)
    assert (rows["Beta"].d61_90_cents, rows["Beta"].over_90_cents, rows["Beta"].total_cents) == (30000, 40000, 70000)
    assert rows["Beta"].invoice_count == 2 and rows["Alfa"].overdue_cents == 20000
    ordered = [r.contact_name for r in debiteuren_overview(session, TODAY)]
    assert ordered == ["Beta", "Alfa"]  # largest first
    total = debtor_totals(list(rows.values()))
    assert (total.total_cents, total.not_due_cents, total.over_90_cents) == (100000, 10000, 40000)
    s = stats(session, TODAY)
    assert (s.total_open_cents, s.overdue_cents, s.open_count, s.concept_count) == (100000, 90000, 4, 1)


def test_ageing_boundaries_use_days_past_due(session, make_final, customer):
    # due dates exactly 30 / 31 days before today
    make_final(customer, day=date(2026, 4, 30), lines=one_line(100))  # due 05-30: 31 days -> 31-60
    make_final(customer, day=date(2026, 5, 1), lines=one_line(200))  # due 05-31: 30 days -> 1-30
    row = debiteuren_overview(session, TODAY)[0]
    assert (row.d1_30_cents, row.d31_60_cents) == (200, 100)


def test_credit_notes_and_payments_reduce_open_amounts(session, make_final, customer, storage):
    inv = make_final(customer, day=date(2026, 6, 1), lines=one_line(10000))
    inv.paid_cents = 2500
    session.commit()
    row = debiteuren_overview(session, TODAY)[0]
    assert row.total_cents == 7500
    note = create_credit_concept(session, inv.id, today=date(2026, 6, 10))
    finalize(session, note.id, storage=storage)
    session.commit()
    # 100 credited, 25 paid -> 75 set off, 25 owed back to the klant
    assert [r.total_cents for r in debiteuren_overview(session, TODAY)] == [-2500]
    items = debtor_open_items(session, customer.id, TODAY)
    assert [(i.kind, i.open_cents) for i in items] == [("credit_note", -2500)]
    assert stats(session, TODAY).total_open_cents == -2500


def test_opening_debtor_items_are_part_of_overview(session, customer, year2026, acc):
    book_opening_balance(
        session,
        OpeningInput(
            [(acc("1210"), 100000)],
            [OpeningItemInput("debiteur", customer.id, "OLD-1", date(2025, 11, 1), date(2025, 12, 1), 5000)],
        ),
        year=2026,
    )
    session.commit()
    row = debiteuren_overview(session, TODAY)[0]
    assert (row.over_90_cents, row.opening_count, row.invoice_count) == (5000, 1, 1)
    assert [i.source for i in debtor_open_items(session, customer.id, TODAY)] == ["opening_item"]
    assert stats(session, TODAY).total_open_cents == 5000


def test_list_documents_filters_search_and_pagination(session, make_final, make_concept, make_customer):
    a, b = make_customer("Alfa"), make_customer("Beta")
    make_final(b, day=date(2026, 4, 1), lines=one_line(3000))  # late
    paid = make_final(a, day=date(2026, 5, 1), lines=one_line(1000))
    paid.paid_cents = 1000
    session.commit()
    make_final(a, day=date(2026, 6, 20), lines=one_line(2000))  # not due on TODAY
    make_concept(b, lines=one_line(4000))

    def names(**kw):
        page = list_documents(session, today=TODAY, **kw)
        return [(r.contact_name, r.status) for r in page.items]

    assert len(list_documents(session, today=TODAY).items) == 4
    assert names(status="concept") == [("Beta", "concept")]
    assert names(status="openstaand") == [("Alfa", "openstaand")]
    assert names(status="te_laat") == [("Beta", "te_laat")]
    assert names(status="betaald") == [("Alfa", "betaald")]
    assert {n for n, _ in names(q="alfa")} == {"Alfa"}
    assert names(q="2026-0001") == [("Beta", "te_laat")]
    page = list_documents(session, today=TODAY, per_page=3, page=2)
    assert (page.total, len(page.items), page.pages) == (4, 1, 2)
    row = list_documents(session, today=TODAY, status="te_laat").items[0]
    assert row.number == "2026-0001" and row.total_cents == 3000 and row.open_cents == 3000 and row.is_overdue
    concept_row = list_documents(session, today=TODAY, status="concept").items[0]
    assert concept_row.number is None and concept_row.due_date is None


def test_credit_note_rows_are_negative(session, make_final, customer, storage):
    inv = make_final(customer, day=date(2026, 6, 1), lines=one_line(10000))
    note = create_credit_concept(session, inv.id, today=date(2026, 6, 10))
    finalize(session, note.id, storage=storage)
    session.commit()
    rows = {r.kind: r for r in list_documents(session, today=TODAY).items}
    assert rows["credit_note"].total_cents == -10000 and rows["credit_note"].credited_number == inv.number
    assert rows["invoice"].open_cents == 0 and rows["invoice"].status == "gecrediteerd"
