from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.ledger import lock_period
from app.domain.vat.icp import build_icp, couple_entry_contact, suggest_contact
from app.domain.vat.report import build_vat_report
from app.models import Period
from sqlalchemy import select
from tests.vat.vat_helpers import DAY, Q3, Book, insert_return, link_invoice, make_contact, rubriek


@pytest.fixture
def book(session):
    return Book(session)


def eu_sale(book, cents, *, code="EU_GOEDEREN", day=DAY, desc="Verkoop EU"):
    return book.sale(cents, 0, code=code, revenue="8404", day=day, desc=desc)


def icp(session):
    return build_icp(session, *Q3)


def test_klant_from_sales_invoice_buyer(session, book):
    c = make_contact(session)
    e = eu_sale(book, 50000)
    link_invoice(session, e, c)
    r = icp(session)
    assert len(r.rows) == 1
    row = r.rows[0]
    assert (row.country, row.btw_number, row.goederen_cents, row.diensten_cents, row.driehoek_cents) == (
        "DE", "123456789", 50000, 0, 0)
    assert row.contact_id == c.id and row.issue is None
    assert r.unassigned == []


def test_goederen_and_diensten_split_and_summed_per_klant(session, book):
    c = make_contact(session)
    link_invoice(session, eu_sale(book, 50000), c)
    link_invoice(session, eu_sale(book, 25000), c)
    link_invoice(session, eu_sale(book, 10000, code="EU_DIENSTEN"), c)
    row = icp(session).rows[0]
    assert (row.goederen_cents, row.diensten_cents) == (75000, 10000)


def test_normalisation_merges_spaced_and_lowercase_numbers(session, book):
    c = make_contact(session)
    link_invoice(session, eu_sale(book, 100), c, btw="de 123.456-789")
    link_invoice(session, eu_sale(book, 200), c, btw="DE123456789")
    r = icp(session)
    assert [(x.country, x.btw_number, x.goederen_cents) for x in r.rows] == [("DE", "123456789", 300)]


def test_coupling_used_when_no_invoice(session, book):
    c = make_contact(session, btw="FR12345678901", country="FR")
    e = eu_sale(book, 40000)
    assert [u.entry_id for u in icp(session).unassigned] == [e.id]
    couple_entry_contact(session, e.id, c.id)
    r = icp(session)
    assert r.unassigned == []
    assert (r.rows[0].country, r.rows[0].btw_number) == ("FR", "12345678901")


def test_invoice_wins_over_coupling(session, book):
    a = make_contact(session, name="A", btw="DE111111111")
    b = make_contact(session, name="B", btw="BE222222222", country="BE")
    e = eu_sale(book, 1000)
    link_invoice(session, e, a, btw="DE111111111")
    couple_entry_contact(session, e.id, b.id)
    assert [x.btw_number for x in icp(session).rows] == ["111111111"]


def test_storno_follows_original_klant_and_nets_out(session, book):
    c = make_contact(session)
    e = eu_sale(book, 50000)
    link_invoice(session, e, c)
    book.reverse(e)
    r = icp(session)
    assert r.rows == [] and r.unassigned == []


def test_unassigned_entry_listed_with_amounts(session, book):
    e = eu_sale(book, 30000, code="EU_DIENSTEN", desc="Consult Berlijn")
    u = icp(session).unassigned[0]
    assert (u.entry_id, u.entry_number, u.diensten_cents, u.goederen_cents, u.description) == (
        e.id, e.entry_number, 30000, 0, "Consult Berlijn")


def test_klant_netting_to_zero_is_omitted(session, book):
    c = make_contact(session)
    link_invoice(session, eu_sale(book, 5000), c)
    cn = book.credit_note(5000, 0, code="EU_GOEDEREN", revenue="8404")
    link_invoice(session, cn, c)
    assert icp(session).rows == []


def test_nl_klant_and_missing_btw_are_incomplete_with_fix(session, book):
    nl = make_contact(session, name="Hollander", country="NL", btw="NL123456789B01")
    nobtw = make_contact(session, name="Zonder", country="DE", btw=None)
    link_invoice(session, eu_sale(book, 100), nl, btw="NL123456789B01", country="NL", name="Hollander")
    link_invoice(session, eu_sale(book, 200), nobtw, btw=None, country="DE", name="Zonder")
    rows = {r.name: r for r in icp(session).rows}
    assert "Relaties" in rows["Zonder"].issue and "btw-nummer" in rows["Zonder"].issue
    assert rows["Zonder"].btw_number == "" and rows["Zonder"].country == "DE"
    assert rows["Hollander"].issue is not None and "Nederland" in rows["Hollander"].issue


def test_other_3b_code_counts_as_goederen_with_warning(session, book):
    from app.domain.vat.service import add_vat_code

    add_vat_code(session, code="EU_X", name="EU anders", rate_percent_text="0", sales_rubriek="3b")
    c = make_contact(session)
    link_invoice(session, eu_sale(book, 700, code="EU_X"), c)
    r = icp(session)
    assert r.rows[0].goederen_cents == 700
    assert [w.code for w in r.warnings] == ["ICP_UNCLEAR"]


def test_total_equals_3b_grondslag_and_no_mismatch_warning(session, book):
    c = make_contact(session)
    link_invoice(session, eu_sale(book, 5000), c)
    eu_sale(book, 7000, code="EU_DIENSTEN")
    r = icp(session)
    total = sum(x.goederen_cents + x.diensten_cents for x in r.rows) + sum(
        u.goederen_cents + u.diensten_cents for u in r.unassigned)
    assert total == rubriek(build_vat_report(session, *Q3), "3b").grondslag_cents == 12000
    assert not any(w.code == "ICP_MISMATCH" for w in r.warnings)


def test_period_and_opening_boundaries(session, book):
    eu_sale(book, 100, day=date(2026, 6, 30))
    assert icp(session).unassigned == []


def test_w4_disappears_after_coupling(session, book):
    c = make_contact(session)
    e = eu_sale(book, 100)
    assert any(w.code == "W4" for w in build_vat_report(session, *Q3).warnings)
    couple_entry_contact(session, e.id, c.id)
    assert not any(w.code == "W4" for w in build_vat_report(session, *Q3).warnings)


def test_coupling_replaces_existing(session, book):
    a = make_contact(session, name="A", btw="DE111111111")
    b = make_contact(session, name="B", btw="BE222222222", country="BE")
    e = eu_sale(book, 100)
    couple_entry_contact(session, e.id, a.id)
    couple_entry_contact(session, e.id, b.id)
    assert [x.btw_number for x in icp(session).rows] == ["222222222"]


def test_coupling_refused_in_locked_period(session, book):
    c = make_contact(session)
    e = eu_sale(book, 100)
    pid = session.scalar(select(Period.id).where(Period.start_date <= DAY, Period.end_date >= DAY))
    lock_period(session, pid)
    with pytest.raises(LedgerError) as exc:
        couple_entry_contact(session, e.id, c.id)
    assert exc.value.code == "VAT_ENTRY_LOCKED"
    assert exc.value.message == (
        "Deze boeking zit in een vergrendelde periode, dus je kunt er geen klant meer aan koppelen.")


def test_coupling_refused_in_filed_return_range(session, book):
    c = make_contact(session)
    e = eu_sale(book, 100)
    insert_return(session, 2026, "quarter", 3)
    with pytest.raises(LedgerError) as exc:
        couple_entry_contact(session, e.id, c.id)
    assert exc.value.code == "VAT_ENTRY_LOCKED"


def test_coupling_unknown_entry_or_contact(session, book):
    c = make_contact(session)
    with pytest.raises(LedgerError) as e1:
        couple_entry_contact(session, 9999, c.id)
    assert e1.value.code == "VAT_ENTRY_NOT_FOUND"
    e = eu_sale(book, 100)
    with pytest.raises(LedgerError) as e2:
        couple_entry_contact(session, e.id, 9999)
    assert e2.value.code == "VAT_CONTACT_NOT_FOUND"


def test_suggest_contact_from_description(session, book):
    c = make_contact(session, name="Müller GmbH")
    make_contact(session, name="Andere BV", btw="DE999999999")
    e = eu_sale(book, 100, desc="Factuur Muller GmbH maart")
    assert suggest_contact(session, e.id).id == c.id
    e2 = eu_sale(book, 100, desc="Iets anders")
    assert suggest_contact(session, e2.id) is None
