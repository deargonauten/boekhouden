"""Pure entry building: sign of the bank line, 3000/1400 lines, validation messages."""

from datetime import date

import pytest

from app.domain.reconcile.entries import SystemAccounts, build_payment_entry
from app.domain.reconcile.errors import ReconcileError
from app.domain.reconcile.types import AllocationLine, DirectLine, TxnView

BANK, CRED, VAT, COST = 1210, 3000, 1400, 4200
ACC = SystemAccounts(creditors=CRED, vat_receivable=VAT)
RATES = {"NL_21": 2100, "NL_9": 900, "NL_0": 0, "GEEN": 0}


def txn(amount, desc="Betaling", ref=None):
    return TxnView(1, date(2025, 4, 1), amount, "Bol", "NL91ABNA0417164300", desc, ref)


def alloc(amount, number="F-1", credit=False, open_=None, sid=1):
    return AllocationLine("purchase_invoice", sid, amount, credit, number, open_ if open_ is not None else amount)


def build(t, allocs=(), directs=(), rates=RATES):
    return build_payment_entry(
        t, bank_account_id=BANK, journal_id=7, allocations=allocs, direct_lines=directs,
        accounts=ACC, vat_rates=rates,
    )


def totals(entry):
    return sum(l.debit_cents for l in entry.lines), sum(l.credit_cents for l in entry.lines)


def line(entry, account):
    return [l for l in entry.lines if l.account_id == account]


def test_pay_invoice_debits_creditors_credits_bank():
    e = build(txn(-12100), [alloc(12100)])
    assert totals(e) == (12100, 12100)
    assert line(e, CRED)[0].debit_cents == 12100
    assert line(e, BANK)[0].credit_cents == 12100
    assert e.journal_id == 7 and e.booking_date == date(2025, 4, 1) and e.reference == "F-1"


def test_split_one_creditors_line_per_allocation():
    e = build(txn(-30000), [alloc(10000, "F-1", sid=1), alloc(20000, "F-2", sid=2)])
    assert [l.debit_cents for l in line(e, CRED)] == [10000, 20000]
    assert e.reference == "F-1, F-2"
    assert totals(e) == (30000, 30000)


def test_credit_note_refund_debits_bank_credits_creditors():
    e = build(txn(5000), [alloc(5000, "C-1", credit=True)])
    assert line(e, BANK)[0].debit_cents == 5000
    assert line(e, CRED)[0].credit_cents == 5000


def test_mixed_invoice_and_credit_note_net_must_match():
    e = build(txn(-8000), [alloc(10000, "F-1", sid=1), alloc(2000, "C-1", credit=True, sid=2)])
    assert totals(e) == (10000, 10000)
    assert line(e, BANK)[0].credit_cents == 8000
    assert line(e, CRED)[0].debit_cents == 10000 and line(e, CRED)[1].credit_cents == 2000


def test_direct_af_splits_vat_to_1400():
    e = build(txn(-12100), directs=[DirectLine(COST, 12100, "NL_21", "Papier")])
    cost, vat = line(e, COST)[0], line(e, VAT)[0]
    assert (cost.debit_cents, cost.vat_code) == (10000, "NL_21")
    assert vat.debit_cents == 2100
    assert line(e, BANK)[0].credit_cents == 12100
    assert totals(e) == (12100, 12100)


def test_direct_vat_rounding_half_up_and_balanced():
    e = build(txn(-1000), directs=[DirectLine(COST, 1000, "NL_21")])  # 1000*21/121 = 173.55 -> 174
    assert line(e, VAT)[0].debit_cents == 174
    assert line(e, COST)[0].debit_cents == 826
    assert totals(e) == (1000, 1000)


def test_direct_zero_vat_has_no_1400_line():
    e = build(txn(-2500), directs=[DirectLine(COST, 2500, "GEEN")])
    assert line(e, VAT) == []
    assert len(e.lines) == 2


def test_direct_vat_aggregated_per_code():
    e = build(txn(-2420), directs=[DirectLine(COST, 1210, "NL_21"), DirectLine(4300, 1210, "NL_21")])
    assert len(line(e, VAT)) == 1 and line(e, VAT)[0].debit_cents == 420


def test_direct_bij_credits_account_and_debits_bank():
    e = build(txn(2000), directs=[DirectLine(8900, 2000, "GEEN", "Rente")])
    assert line(e, BANK)[0].debit_cents == 2000
    assert line(e, 8900)[0].credit_cents == 2000


def test_direct_bij_with_vat_refused():
    with pytest.raises(ReconcileError) as exc:
        build(txn(2000), directs=[DirectLine(8900, 2000, "NL_21")])
    assert "alleen zonder BTW" in exc.value.message


def test_unsupported_vat_code_refused():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-2000), directs=[DirectLine(COST, 2000, "VERLEGD")])
    assert "BTW" in exc.value.message


def test_combine_invoice_and_direct_lines():
    e = build(txn(-12600), [alloc(12100)], [DirectLine(COST, 500, "GEEN", "Bankkosten")])
    assert totals(e) == (12600, 12600)
    assert line(e, BANK)[0].credit_cents == 12600


def test_remainder_message():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-12100), [alloc(11000)])
    assert exc.value.message == "Er is nog € 11,00 niet verdeeld." or "niet verdeeld" in exc.value.message
    assert "€ 11,00" in exc.value.message


def test_too_much_distributed_message():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-1000), [alloc(1500, open_=1500)])
    assert "meer verdeeld" in exc.value.message and "€ 5,00" in exc.value.message


def test_over_allocation_of_an_invoice_message():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-20000), [alloc(20000, open_=12100)])
    assert exc.value.message == "Je kunt maximaal € 121,00 aan deze factuur toewijzen; er staat nog € 121,00 open."


def test_nothing_to_book_refused():
    with pytest.raises(ReconcileError):
        build(txn(-100))


def test_direction_rules_for_documents():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-5000), [alloc(5000, "C-1", credit=True)])
    assert "alleen koppelen aan inkoopfacturen" in exc.value.message
    with pytest.raises(ReconcileError):
        build(txn(5000), [alloc(5000, "F-1")])


def test_direct_line_needs_account_and_positive_amount():
    with pytest.raises(ReconcileError) as exc:
        build(txn(-100), directs=[DirectLine(None, 100, "GEEN")])
    assert exc.value.message == "Kies een rekening voor deze regel."
    with pytest.raises(ReconcileError):
        build(txn(-100), directs=[DirectLine(COST, 0, "GEEN"), DirectLine(COST, 100, "GEEN")])


def test_direct_line_needs_vat_code():
    with pytest.raises(ReconcileError):
        build(txn(-100), directs=[DirectLine(COST, 100, None)])


def test_zero_allocation_refused():
    with pytest.raises(ReconcileError):
        build(txn(-100), [alloc(0)], [DirectLine(COST, 100, "GEEN")])


def test_reference_falls_back_to_bank_reference():
    e = build(txn(-100, ref="REF42"), directs=[DirectLine(COST, 100, "GEEN")])
    assert e.reference == "REF42"
