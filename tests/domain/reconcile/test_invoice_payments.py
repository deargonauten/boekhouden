"""Which unprocessed bank transactions could be the payment of an invoice under review."""

from datetime import date

from app.domain.reconcile.invoice_payments import InvoiceView, payment_candidates
from app.domain.reconcile.types import TxnView

IBAN = "NL91ABNA0417164300"


def invoice(total=12100, number="F-2026/001", is_credit=False, name="Bol B.V.", iban=IBAN, on=date(2025, 3, 1)):
    return InvoiceView(
        number=number, invoice_date=on, total_incl_cents=total, is_credit=is_credit,
        supplier_name=name, supplier_iban=iban,
    )


def txn(id_=1, amount=-12100, desc="Betaling", name="Anders", iban=None, on=date(2025, 3, 10)):
    return TxnView(
        id=id_, booking_date=on, amount_cents=amount, counterparty_name=name,
        counterparty_iban=iban, description=desc,
    )


def ids(found):
    return [c.txn.id for c in found]


def test_exact_amount_is_a_candidate():
    found = payment_candidates(invoice(), [txn()])
    assert ids(found) == [1]
    assert "Het bedrag klopt precies" in found[0].reasons


def test_unrelated_transaction_is_not_a_candidate():
    assert payment_candidates(invoice(), [txn(amount=-999)]) == []


def test_invoice_number_in_description_allows_a_partial_payment():
    found = payment_candidates(invoice(), [txn(amount=-5000, desc="deel F2026001")])
    assert ids(found) == [1]
    assert any("deel" in r for r in found[0].reasons)


def test_iban_match_allows_a_partial_payment():
    assert ids(payment_candidates(invoice(), [txn(amount=-5000, iban=IBAN)])) == [1]


def test_more_than_the_invoice_is_never_a_candidate():
    assert payment_candidates(invoice(), [txn(amount=-20000, iban=IBAN, desc="F2026001")]) == []


def test_money_in_is_not_a_payment_of_an_invoice():
    assert payment_candidates(invoice(), [txn(amount=12100, iban=IBAN)]) == []


def test_credit_note_is_matched_by_money_in():
    found = payment_candidates(invoice(is_credit=True), [txn(amount=12100), txn(id_=2, amount=-12100)])
    assert ids(found) == [1]


def test_payment_long_before_the_invoice_is_not_a_candidate():
    assert payment_candidates(invoice(), [txn(on=date(2025, 1, 1))]) == []


def test_payment_a_few_days_before_the_invoice_date_still_counts():
    assert ids(payment_candidates(invoice(), [txn(on=date(2025, 2, 27))])) == [1]


def test_best_match_first_then_newest():
    found = payment_candidates(
        invoice(),
        [txn(1), txn(2, iban=IBAN, desc="F2026001"), txn(3, on=date(2025, 3, 12))],
    )
    assert ids(found) == [2, 3, 1]


def test_unknown_amount_gives_no_candidates():
    assert payment_candidates(invoice(total=None), [txn()]) == []


def test_name_only_is_not_enough():
    assert payment_candidates(invoice(), [txn(amount=-5000, name="Bol B.V.")]) == []
