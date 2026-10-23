import json
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.domain.errors import LedgerError
from app.domain.ledger import reverse_entry
from app.domain.vat import filing
from app.domain.vat.filing import file_vat_return, get_return, get_snapshot, list_returns
from app.domain.vat.icp import build_icp
from app.domain.vat.periods import VatPeriod
from app.domain.vat.settings import save_vat_settings
from app.models import FiscalYear, Period, VatReturn
from tests.vat.vat_helpers import Book, link_invoice, make_contact, set_company

TODAY = date(2026, 10, 23)
Q1, Q2, Q3, Q4 = (VatPeriod(2026, "quarter", n) for n in (1, 2, 3, 4))


@pytest.fixture
def book(session):
    b = Book(session)
    set_company(session)
    return b


def fails(code, fn, *a, **kw):
    with pytest.raises(LedgerError) as e:
        fn(*a, **kw)
    assert e.value.code == code
    return e.value.message


def file(session, period, **kw):
    kw.setdefault("filed_on", date(2026, 10, 20))
    kw.setdefault("today", TODAY)
    return file_vat_return(session, period, **kw)


def locked_months(session, year=2026):
    return sorted(session.scalars(
        select(Period.number).join(FiscalYear).where(FiscalYear.year == year, Period.status == "locked")
    ))


def test_filing_locks_exactly_the_months_of_the_quarter(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    filed = file(session, Q3, reference="ONT-123")
    assert locked_months(session) == [7, 8, 9]
    assert filed.reference == "ONT-123" and filed.filed_on == date(2026, 10, 20)
    assert filed.total_cents == 21000
    assert get_return(session, Q3).snapshot.status == "ingediend"
    row = session.scalar(select(VatReturn))
    assert (row.year, row.kind, row.number, row.status) == (2026, "quarter", 3, "ingediend")
    assert (row.start_date, row.end_date) == (date(2026, 7, 1), date(2026, 9, 30))


def test_month_filing_locks_only_that_month(session, book):
    book.sale(10000, 2100, day=date(2026, 8, 3))
    file(session, VatPeriod(2026, "month", 8))
    assert locked_months(session) == [8]


def test_nihilaangifte_can_be_filed(session, book):
    f = file(session, Q3)
    assert f.total_cents == 0 and locked_months(session) == [7, 8, 9]


def test_q4_closes_the_fiscal_year(session, book):
    for q in (Q1, Q2, Q3, Q4):
        file(session, q, filed_on=date(2026, 10, 1))
    assert session.scalar(select(FiscalYear.status).where(FiscalYear.year == 2026)) == "closed"


def test_double_filing_refused(session, book):
    file(session, Q3)
    msg = fails("VAT_ALREADY_FILED", file, session, Q3)
    assert msg == "Deze aangifte is al ingediend en kan niet meer worden aangepast."


def test_overlapping_other_kind_refused(session, book):
    file(session, Q3)
    fails("VAT_ALREADY_FILED", file, session, VatPeriod(2026, "month", 8))


def test_out_of_order_refused_when_earlier_has_entries(session, book):
    book.sale(10000, 2100, day=date(2026, 2, 3))
    msg = fails("VAT_EARLIER_NOT_FILED", file, session, Q2)
    assert msg == "Dien eerst de aangifte over 1e kwartaal 2026 in, daarna deze."
    assert locked_months(session) == []


def test_out_of_order_ok_when_earlier_period_empty_or_kor(session, book):
    file(session, Q3)  # Q1 and Q2 have no entries
    book.sale(10000, 2100, day=date(2026, 11, 3))
    book.sale(10000, 2100, day=date(2026, 2, 3))
    save_vat_settings(session, "quarter", date(2026, 1, 1), date(2026, 3, 31), today=TODAY)  # Q1 is KOR
    file(session, Q4)


def test_out_of_order_ok_after_filing_earlier(session, book):
    book.sale(10000, 2100, day=date(2026, 2, 3))
    file(session, Q1)
    file(session, Q2)


def test_future_filed_on_refused(session, book):
    msg = fails("VAT_FUTURE_DATE", file, session, Q3, filed_on=date(2026, 10, 24))
    assert msg == "De datum van indienen kan niet in de toekomst liggen."
    file(session, Q3, filed_on=TODAY)  # today itself is fine


def test_kor_period_cannot_be_filed_but_icp_still_works(session, book):
    save_vat_settings(session, "quarter", date(2026, 7, 1), None, today=TODAY)
    c = make_contact(session)
    e = book.sale(5000, 0, code="EU_GOEDEREN", revenue="8040", day=date(2026, 8, 3))
    link_invoice(session, e, c)
    msg = fails("VAT_KOR_NO_RETURN", file, session, Q3)
    assert msg == "Je gebruikt de KOR in deze periode, dus je hoeft geen btw-aangifte te doen."
    assert build_icp(session, date(2026, 7, 1), date(2026, 9, 30)).rows[0].goederen_cents == 5000
    assert locked_months(session) == []


def test_partial_kor_can_be_filed(session, book):
    save_vat_settings(session, "month", date(2026, 8, 1), None, today=TODAY)
    file(session, Q3)


def test_company_btw_id_required(session, book):
    set_company(session, btw_id=None)
    msg = fails("VAT_COMPANY_INCOMPLETE", file, session, Q3)
    assert msg == "Vul eerst je btw-nummer in onder Instellingen > Bedrijfsgegevens."


def test_company_profile_missing(session):
    Book(session)
    fails("VAT_COMPANY_INCOMPLETE", file, session, Q3)


def test_missing_fiscal_year(session, book):
    msg = fails("VAT_PERIOD_MISSING", file, session, VatPeriod(2027, "quarter", 1), filed_on=date(2026, 10, 1))
    assert msg == "Het boekjaar 2027 bestaat nog niet. Maak het eerst aan onder Instellingen > Boekjaren."


def test_snapshot_is_frozen_and_unchanged_after_later_ledger_changes(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    filed = file(session, Q3)
    before = get_snapshot(session, Q3, today=TODAY)
    book.sale(55500, 11655, day=date(2026, 11, 3))  # later quarter
    book.sale(1000, 210, day=date(2026, 10, 1))
    after = get_snapshot(session, Q3, today=TODAY)
    assert before == after == filed.snapshot
    assert after.totals["5g"] == 21000 and not after.is_concept and after.status == "ingediend"
    assert after.company_name == "Jansen Advies" and after.btw_id == "NL123456789B01"
    assert after.filed_on == date(2026, 10, 20)


def test_concept_snapshot_is_live(session, book):
    book.sale(100000, 21000, day=date(2026, 8, 3))
    s = get_snapshot(session, Q3, today=TODAY)
    assert s.is_concept and s.status == "concept" and s.filed_on is None
    book.sale(100000, 21000, day=date(2026, 8, 4))
    assert get_snapshot(session, Q3, today=TODAY).totals["5g"] == 42000


def test_snapshot_json_has_only_ints_and_strings(session, book):
    c = make_contact(session)
    link_invoice(session, book.sale(5000, 0, code="EU_DIENSTEN", revenue="8040", day=date(2026, 8, 3)), c)
    book.sale(10000, 2100, day=date(2026, 8, 3))
    file(session, Q3)
    data = json.loads(session.scalar(select(VatReturn.snapshot_json)))

    def walk(v):
        assert not isinstance(v, float), v
        if isinstance(v, dict):
            [walk(x) for x in v.values()]
        elif isinstance(v, list):
            [walk(x) for x in v]

    walk(data)
    snap = get_return(session, Q3).snapshot
    assert snap.icp[0].diensten_cents == 5000 and snap.icp[0].country == "DE"
    assert snap.period == Q3 and snap.lines[0].rubriek == "1a"


def test_posting_or_storno_into_locked_period_still_fails(session, book):
    e = book.sale(10000, 2100, day=date(2026, 8, 3))
    file(session, Q3)
    with pytest.raises(LedgerError) as exc:
        book.sale(10000, 2100, day=date(2026, 9, 1))
    assert exc.value.code == "PERIOD_LOCKED"
    with pytest.raises(LedgerError) as exc:
        reverse_entry(session, e.id, booking_date=date(2026, 9, 2))
    assert exc.value.code == "PERIOD_LOCKED"
    # storno in the open period shows up in that period's aangifte
    reverse_entry(session, e.id, booking_date=date(2026, 10, 5))
    assert get_snapshot(session, Q4, today=TODAY).totals["5g"] == -2100


def test_triggers_block_delete(session, book):
    file(session, Q3)
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("DELETE FROM vat_return"))
    session.rollback()


def test_trigger_blocks_update(session, book):
    file(session, Q3)
    session.commit()
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE vat_return SET total_cents = 5"))
    session.rollback()
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE vat_return SET snapshot_json = '{}'"))
    session.rollback()


def test_reference_can_be_set_once_when_null(session, book):
    file(session, Q3)
    session.execute(text("UPDATE vat_return SET reference = 'REF1'"))
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE vat_return SET reference = 'REF2'"))
    session.rollback()


def test_failure_midway_leaves_periods_open_and_no_return(session, book, monkeypatch):
    book.sale(10000, 2100, day=date(2026, 8, 3))
    session.commit()
    real = filing.lock_period
    calls = []

    def flaky(s, period_id):
        calls.append(period_id)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(s, period_id)

    monkeypatch.setattr(filing, "lock_period", flaky)
    with pytest.raises(RuntimeError):
        file(session, Q3)
    assert locked_months(session) == []
    assert session.scalar(select(VatReturn.id)) is None


def test_list_returns_status_amount_deadline(session, book):
    book.sale(100000, 21000, day=date(2026, 2, 3))
    file(session, Q1)
    book.sale(10000, 2100, day=date(2026, 5, 3))
    rows = {r.period.number: r for r in list_returns(session, 2026, "quarter", today=TODAY)}
    assert rows[1].status == "ingediend" and rows[1].total_cents == 21000
    assert rows[1].filed_on == date(2026, 10, 20)
    assert rows[2].status == "concept" and rows[2].total_cents == 2100 and rows[2].overdue
    assert rows[3].status == "niet_gestart" and rows[3].total_cents is None and not rows[3].overdue
    assert rows[4].deadline == date(2027, 1, 31)
    assert all(r.kor == "none" for r in rows.values())


def test_list_returns_shows_kor(session, book):
    save_vat_settings(session, "quarter", date(2026, 10, 1), None, today=TODAY)
    rows = list_returns(session, 2026, "quarter", today=TODAY)
    assert [r.kor for r in rows] == ["none", "none", "none", "full"]


def test_w6_clears_after_earlier_period_filed(session, book):
    from app.domain.vat.report import build_vat_report

    book.sale(10000, 2100, day=date(2026, 2, 3))
    assert any(w.code == "W6" for w in build_vat_report(session, date(2026, 4, 1), date(2026, 6, 30)).warnings)
    file(session, Q1)
    assert not any(w.code == "W6" for w in build_vat_report(session, date(2026, 4, 1), date(2026, 6, 30)).warnings)


def test_vat_code_rubriek_lock_unchanged_after_filing(session, book):
    from app.domain.vat import update_vat_code

    book.sale(10000, 2100, day=date(2026, 8, 3))
    file(session, Q3)
    fails("VAT_CODE_IN_LOCKED_PERIOD", update_vat_code, session, "NL_21", name="x",
          sales_rubriek="1b", purchase_rubriek="5b")


def test_other_kind_in_same_year_refused_even_without_overlap(session, book):
    file(session, Q1)
    msg = fails("VAT_FREQUENCY_CONFLICT", file, session, VatPeriod(2026, "month", 4))
    assert "kwartaal" in msg and "maand" in msg
