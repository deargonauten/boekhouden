"""Snelkeuzes bij het verwerken van een bankmutatie: btw-aangifte en privé."""

from datetime import date

import pytest

from app.domain.reconcile import ReconcileError, book
from app.domain.reconcile.quick import QUICK_PRIVATE, QUICK_VAT_RETURN, quick_line, vat_period_choices
from tests.domain.reconcile.test_service import balance


def test_private_withdrawal_books_to_prive_opnamen(session, make_txn, year2025):
    t = make_txn(-50000, "Overboeking privé", iban=None)
    book(session, t.id, [], [quick_line(session, t.id, QUICK_PRIVATE)])
    session.commit()
    assert balance(session, "1210") == -50000 and balance(session, "2010") == 50000


def test_private_deposit_books_to_prive_stortingen(session, make_txn, year2025):
    t = make_txn(20000, "Storting", iban=None)
    book(session, t.id, [], [quick_line(session, t.id, QUICK_PRIVATE)])
    session.commit()
    assert balance(session, "1210") == 20000 and balance(session, "2020") == -20000


def test_vat_payment_books_to_btw_rekening_courant(session, make_txn, year2025):
    t = make_txn(-123400, "Belastingdienst", iban=None)
    line = quick_line(session, t.id, QUICK_VAT_RETURN, "2025-Q1")
    assert "1e kwartaal 2025" in line.description
    book(session, t.id, [], [line])
    session.commit()
    assert balance(session, "1210") == -123400 and balance(session, "3150") == 123400


def test_vat_refund_credits_btw_rekening_courant(session, make_txn, year2025):
    t = make_txn(8000, "Teruggaaf btw", iban=None)
    book(session, t.id, [], [quick_line(session, t.id, QUICK_VAT_RETURN, "2025-M02")])
    session.commit()
    assert balance(session, "1210") == 8000 and balance(session, "3150") == -8000


def test_vat_without_period_is_allowed(session, make_txn, year2025):
    t = make_txn(-100, iban=None)
    assert quick_line(session, t.id, QUICK_VAT_RETURN, "").description == "Btw-aangifte"


@pytest.mark.parametrize("bad", ["2025-Q5", "abc", "2025-X1", "2025-M13"])
def test_unknown_period_is_refused_in_plain_dutch(session, make_txn, year2025, bad):
    t = make_txn(-100, iban=None)
    with pytest.raises(ReconcileError) as exc:
        quick_line(session, t.id, QUICK_VAT_RETURN, bad)
    assert "aangifte" in exc.value.message.lower()


def test_unknown_kind_is_refused(session, make_txn, year2025):
    t = make_txn(-100, iban=None)
    with pytest.raises(ReconcileError):
        quick_line(session, t.id, "iets", None)


def test_period_choices_cover_year_of_transaction_and_before(session, make_txn, year2025):
    t = make_txn(-100, iban=None, day=date(2025, 4, 20))
    values = [c.value for c in vat_period_choices(session, t.id)]
    assert "2025-Q1" in values and "2025-Q4" in values and "2024-Q4" in values
