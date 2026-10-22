"""Crediteuren overview with openstaande posten from the beginbalans (openingsbalans AC 12)."""

from datetime import date

import pytest

from app.domain.ledger import trial_balance
from app.domain.opening import OpeningInput, OpeningItemInput, book_opening_balance
from app.domain.purchase import book_extraction, open_by_supplier

TODAY = date(2025, 5, 1)


def cred(contact, number, amount, due=None):
    return OpeningItemInput("crediteur", contact.id, number, date(2024, 12, 1), due, amount)


@pytest.fixture
def opened(session, year2025, make_supplier, make_extraction, acc):
    bol = make_supplier("Bol B.V.")
    plaza = make_supplier("Kantoor Plaza")
    klant = make_supplier("Klant die ook levert")
    book_opening_balance(
        session,
        OpeningInput(
            [(acc("1210"), 100000)],
            [
                cred(bol, "OUD-1", 30000, due=date(2025, 1, 31)),
                cred(plaza, "OUD-2", 4500),
                OpeningItemInput("debiteur", klant.id, "V-1", date(2024, 12, 1), None, 9900),
            ],
        ),
    )
    session.commit()
    book_extraction(session, make_extraction(contact=bol, number="A1").id)  # 121,00
    session.commit()
    return dict(bol=bol, plaza=plaza, klant=klant)


def test_open_by_supplier_includes_opening_posten(session, opened):
    overview = open_by_supplier(session, today=TODAY)
    rows = {r.supplier_name: r for r in overview.rows}
    assert rows["Bol B.V."].invoice_count == 2
    assert rows["Bol B.V."].opening_count == 1
    assert rows["Bol B.V."].open_cents == 30000 + 12100
    assert rows["Bol B.V."].overdue_count == 1  # OUD-1 was due 31-01
    assert rows["Kantoor Plaza"].opening_count == 1 and rows["Kantoor Plaza"].open_cents == 4500
    assert "Klant die ook levert" not in rows  # a debiteur post is not something you pay
    assert overview.total_open_cents == 30000 + 12100 + 4500
    assert overview.open_count == 3 and overview.supplier_count == 2


def test_crediteuren_balance_equals_total_open(session, opened):
    balance = {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session)}
    assert -balance["3000"] == open_by_supplier(session, today=TODAY).total_open_cents


def test_search_filters_opening_posten(session, opened):
    assert [r.supplier_name for r in open_by_supplier(session, q="plaza").rows] == ["Kantoor Plaza"]
    only = open_by_supplier(session, q="oud-1").rows
    assert [(r.supplier_name, r.invoice_count, r.opening_count) for r in only] == [("Bol B.V.", 1, 1)]


def test_replaced_opening_posten_drop_out(session, opened, acc):
    book_opening_balance(session, OpeningInput([(acc("1210"), 100000)], []))
    session.commit()
    overview = open_by_supplier(session, today=TODAY)
    assert [(r.supplier_name, r.opening_count, r.open_cents) for r in overview.rows] == [("Bol B.V.", 0, 12100)]
    balance = {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session)}
    assert -balance["3000"] == overview.total_open_cents


def test_default_opening_count_is_zero(session, year2025, make_extraction):
    book_extraction(session, make_extraction(number="Z1").id)
    session.commit()
    assert open_by_supplier(session).rows[0].opening_count == 0
