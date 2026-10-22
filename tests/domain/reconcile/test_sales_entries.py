"""Pure entry building for the sales (debiteuren) side: 1300 lines, directions, mixed sides."""

from datetime import date

import pytest

from app.domain.reconcile.entries import SystemAccounts, build_payment_entry, net_distributed
from app.domain.reconcile.errors import MIXED_SIDES, WRONG_DIRECTION, ReconcileError
from app.domain.reconcile.types import AllocationLine, DirectLine, TxnView

BANK, CRED, VAT, DEBT, COST = 1210, 3000, 1400, 1300, 4200
ACC = SystemAccounts(creditors=CRED, vat_receivable=VAT, debtors=DEBT)
RATES = {"NL_21": 2100, "GEEN": 0}


def txn(amount, desc="Betaling 2026-0007"):
    return TxnView(1, date(2026, 4, 1), amount, "Klant BV", "NL91ABNA0417164300", desc, None)


def sale(amount, number="2026-0007", credit=False, sid=1, open_=None):
    return AllocationLine("sales_invoice", sid, amount, credit, number, open_ if open_ is not None else amount, "debiteur")


def purchase(amount, number="F-1", credit=False, sid=1):
    return AllocationLine("purchase_invoice", sid, amount, credit, number, amount, "crediteur")


def build(t, allocs=(), directs=(), accounts=ACC):
    return build_payment_entry(
        t, bank_account_id=BANK, journal_id=7, allocations=allocs, direct_lines=directs,
        accounts=accounts, vat_rates=RATES,
    )


def sides(entry):
    return set((l.account_id, l.debit_cents, l.credit_cents) for l in entry.lines)


def test_incoming_payment_debits_bank_credits_debtors():
    e = build(txn(12100), [sale(12100)])
    assert sides(e) == {(DEBT, 0, 12100), (BANK, 12100, 0)}
    assert e.reference == "2026-0007"


def test_partial_payment_credits_only_the_paid_part():
    e = build(txn(5000), [sale(5000, open_=12100)])
    assert sides(e) == {(DEBT, 0, 5000), (BANK, 5000, 0)}


def test_several_invoices_one_line_each():
    e = build(txn(30000), [sale(10000, "2026-0001", sid=1), sale(20000, "2026-0002", sid=2)])
    assert sorted(l.credit_cents for l in e.lines if l.account_id == DEBT) == [10000, 20000]
    assert [l.debit_cents for l in e.lines if l.account_id == BANK] == [30000]


def test_refund_of_credit_note_credits_bank_debits_debtors():
    e = build(txn(-5000, "Terugbetaling"), [sale(5000, "2026-0008", credit=True)])
    assert sides(e) == {(DEBT, 5000, 0), (BANK, 0, 5000)}


def test_credit_note_netted_in_incoming_payment():
    # klant pays 121,00 for an invoice of 150,00 minus a credit note of 29,00 in one transfer
    t = txn(12100)
    allocs = [sale(15000, "2026-0001", sid=1), sale(2900, "2026-0002", credit=True, sid=2)]
    e = build(t, allocs)
    assert net_distributed(t, allocs, []) == 12100
    assert sides(e) == {(DEBT, 0, 15000), (DEBT, 2900, 0), (BANK, 12100, 0)}


def test_incoming_payment_cannot_refund_only_credit_notes():
    with pytest.raises(ReconcileError) as exc:
        build(txn(5000), [sale(5000, credit=True)])
    assert exc.value.code == WRONG_DIRECTION
    assert "verkoopfacturen" in exc.value.message


def test_outgoing_payment_cannot_pay_a_sales_invoice():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-12100), [sale(12100)])
    assert exc.value.code == WRONG_DIRECTION
    assert "verkoopcreditnota" in exc.value.message


@pytest.mark.parametrize("amount", [12100, -12100])
def test_mixed_sides_refused_with_plain_message(amount):
    with pytest.raises(ReconcileError) as exc:
        build(txn(amount), [sale(6000, sid=1), purchase(6100, sid=2, credit=amount > 0)])
    assert exc.value.code == MIXED_SIDES
    assert exc.value.message == (
        "Je kunt een betaling niet tegelijk aan verkoop- en inkoopfacturen koppelen. Koppel ze apart."
    )


def test_incoming_with_direct_line_without_vat_next_to_invoice():
    e = build(txn(12600), [sale(12100)], [DirectLine(8000, 500, "GEEN")])
    assert sum(l.debit_cents for l in e.lines) == sum(l.credit_cents for l in e.lines) == 12600


def test_incoming_direct_line_with_vat_still_refused():
    from app.domain.reconcile.errors import VAT_ON_INCOMING

    with pytest.raises(ReconcileError) as exc:
        build(txn(12100), [], [DirectLine(8000, 12100, "NL_21")])
    assert exc.value.code == VAT_ON_INCOMING


def test_missing_debtors_account_is_a_plain_error():
    with pytest.raises(ReconcileError) as exc:
        build(txn(12100), [sale(12100)], accounts=SystemAccounts(CRED, VAT))
    assert "1300" in exc.value.message


def test_crediteur_rules_unchanged():
    e = build(txn(-12100), [purchase(12100)])
    assert sides(e) == {(CRED, 12100, 0), (BANK, 0, 12100)}
    with pytest.raises(ReconcileError):
        build(txn(-12100), [purchase(12100, credit=True)])
    with pytest.raises(ReconcileError):
        build(txn(12100), [purchase(12100)])
