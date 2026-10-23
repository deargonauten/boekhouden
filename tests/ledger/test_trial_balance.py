from datetime import date

from app.domain.ledger import (
    NewEntry, NewLine, create_fiscal_year, list_fiscal_years, post_entry, trial_balance,
)


def test_trial_balance(session, jrn, acc):
    create_fiscal_year(session, 2025)
    create_fiscal_year(session, 2026)

    def book(day, a, b, cents):
        lines = [NewLine(acc(a), debit_cents=cents), NewLine(acc(b), credit_cents=cents)]
        post_entry(session, NewEntry(jrn("MEM"), day, "t", lines))

    book(date(2025, 1, 5), "1210", "8400", 1000)
    book(date(2025, 2, 5), "1210", "8400", 500)
    book(date(2025, 2, 6), "4625", "1210", 300)
    book(date(2026, 1, 5), "1300", "8400", 77)

    rows = trial_balance(session)
    by = {r.code: r for r in rows}
    assert set(by) == {"1210", "8400", "4625", "1300"}
    assert by["1210"].debit_cents == 1500 and by["1210"].credit_cents == 300
    assert sum(r.debit_cents for r in rows) == sum(r.credit_cents for r in rows)
    assert [r.code for r in rows] == sorted(r.code for r in rows)

    y25 = trial_balance(session, fiscal_year=2025)
    assert {r.code for r in y25} == {"1210", "8400", "4625"}
    assert sum(r.debit_cents for r in y25) == sum(r.credit_cents for r in y25) == 1800

    up = trial_balance(session, up_to=date(2025, 2, 5))
    assert sum(r.debit_cents for r in up) == 1500

    y2025 = [y for y in list_fiscal_years(session) if y.year == 2025][0]
    feb = [p.id for p in y2025.periods if p.number == 2]
    assert sum(r.debit_cents for r in trial_balance(session, period_ids=feb)) == 800
    assert trial_balance(session, period_ids=[]) == []
