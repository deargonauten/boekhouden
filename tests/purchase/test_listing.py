"""Crediteuren overview: list_invoices, open_by_supplier, invoice_status."""

from datetime import date

import pytest

from app.domain.ledger import reverse_entry
from app.domain.purchase import (
    OpenOverview,
    book_extraction,
    invoice_status,
    list_invoices,
    open_amount,
    open_by_supplier,
)

TODAY = date(2025, 5, 1)


@pytest.fixture
def booked(session, year2025, make_extraction, make_supplier):
    bol = make_supplier("Bol B.V.")
    kantoor = make_supplier("Kantoor Plaza")
    a1 = book_extraction(session, make_extraction(contact=bol, number="A1", due_date=date(2025, 4, 1)).id)
    a2 = book_extraction(
        session,
        make_extraction(contact=bol, number="A2", day=date(2025, 3, 20), due_date=date(2025, 6, 1)).id,
    )
    k1 = book_extraction(
        session,
        make_extraction(
            contact=kantoor, number="K1", day=date(2025, 3, 5), lines=[("Stoel", 20000, 4200, "NL_21", "4200")]
        ).id,
    )
    k2 = book_extraction(
        session, make_extraction(contact=kantoor, number="K2", kind="credit_note", day=date(2025, 3, 6)).id
    )
    gone = book_extraction(session, make_extraction(contact=kantoor, number="K3", day=date(2025, 3, 7)).id)
    reverse_entry(session, gone.journal_entry_id)
    session.commit()
    return dict(bol=bol, kantoor=kantoor, a1=a1, a2=a2, k1=k1, k2=k2, gone=gone)


def test_open_amount_and_status():
    assert open_amount("invoice", 12100, 0) == 12100
    assert open_amount("invoice", 12100, 2100) == 10000
    assert open_amount("credit_note", 12100, 0) == -12100
    assert invoice_status(open_cents=12100, reversed=False) == "open"
    assert invoice_status(open_cents=0, reversed=False) == "betaald"
    assert invoice_status(open_cents=12100, reversed=True) == "gestorneerd"
    assert invoice_status(open_cents=-12100, reversed=False) == "open"


def test_list_all(session, booked):
    page = list_invoices(session, today=TODAY)
    assert page.total == 5
    numbers = [r.invoice_number for r in page.items]
    assert numbers == ["A2", "A1", "K3", "K2", "K1"]  # newest invoice date first
    rows = {r.invoice_number: r for r in page.items}
    a1 = rows["A1"]
    assert a1.supplier_name == "Bol B.V."
    assert a1.contact_id == booked["bol"].id
    assert a1.total_cents == 12100 and a1.open_cents == 12100
    assert a1.status == "open" and a1.status_label == "Open"
    assert a1.is_overdue  # due 1-4, today 1-5
    assert a1.document_id == booked["a1"].document_id
    assert a1.journal_entry_id == booked["a1"].journal_entry_id
    assert a1.entry_number.startswith("IK-2025-")
    assert not rows["A2"].is_overdue
    k2 = rows["K2"]
    assert k2.kind == "credit_note" and k2.total_cents == -12100 and k2.open_cents == -12100
    k3 = rows["K3"]
    assert k3.status == "gestorneerd" and k3.status_label == "Gestorneerd"
    assert k3.open_cents == 0 and not k3.is_overdue
    assert k3.storno_entry_id is not None


def test_list_open_tab_excludes_storno(session, booked):
    page = list_invoices(session, tab="open", today=TODAY)
    assert {r.invoice_number for r in page.items} == {"A1", "A2", "K1", "K2"}


@pytest.mark.parametrize("q, expected", [("bol", {"A1", "A2"}), ("k2", {"K2"}), ("PLAZA", {"K1", "K2", "K3"}), ("%", set())])
def test_list_search(session, booked, q, expected):
    assert {r.invoice_number for r in list_invoices(session, q=q).items} == expected


def test_list_pagination(session, booked):
    page = list_invoices(session, page=2, per_page=2)
    assert page.page == 2 and page.pages == 3 and len(page.items) == 2
    last = list_invoices(session, page=99, per_page=2)
    assert last.page == 3 and len(last.items) == 1


def test_open_by_supplier(session, booked):
    overview = open_by_supplier(session, today=TODAY)
    assert isinstance(overview, OpenOverview)
    assert overview.total_open_cents == 12100 + 12100 + 24200 - 12100
    assert overview.open_count == 4
    assert overview.supplier_count == 2
    rows = {r.supplier_name: r for r in overview.rows}
    assert rows["Bol B.V."].invoice_count == 2
    assert rows["Bol B.V."].open_cents == 24200
    assert rows["Bol B.V."].overdue_count == 1
    assert rows["Kantoor Plaza"].invoice_count == 2
    assert rows["Kantoor Plaza"].open_cents == 12100
    assert rows["Kantoor Plaza"].contact_id == booked["kantoor"].id
    assert [r.supplier_name for r in overview.rows] == ["Bol B.V.", "Kantoor Plaza"]  # largest first


def test_open_by_supplier_search(session, booked):
    overview = open_by_supplier(session, q="plaza")
    assert [r.supplier_name for r in overview.rows] == ["Kantoor Plaza"]


def test_empty(session, year2025):
    assert list_invoices(session).total == 0
    overview = open_by_supplier(session)
    assert overview.rows == [] and overview.total_open_cents == 0 and overview.open_count == 0
