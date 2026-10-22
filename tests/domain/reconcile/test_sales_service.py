"""Reconcile service with sales invoices: klant payments, refunds, opening items, undo, end to end."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.domain.ledger import trial_balance
from app.domain.opening import OpeningInput, OpeningItemInput, book_opening_balance
from app.domain.reconcile import (
    Allocation,
    ReconcileError,
    accept,
    book,
    get_transaction_detail,
    list_open_items,
    list_to_process,
    suggestions_for,
    undo,
)
from app.domain.sales import ConceptInput, LineInput, create_credit_concept, finalize, get_detail, open_amount, save_concept
from app.models import BankImportBatch, BankMatch, BankTransaction, OpeningItem, SalesInvoice
from tests.bank.conftest import ING_IBAN, ing_account  # noqa: F401
from tests.ledger.conftest import acc, engine, jrn  # noqa: F401
from tests.sales.conftest import (  # noqa: F401
    DAY,
    company,
    customer,
    make_concept,
    make_customer,
    make_final,
    ready,
    session,
    storage,
    year2026,
)

CUSTOMER_IBAN = "NL91ABNA0417164300"
PAY_DAY = date(2026, 4, 1)


@pytest.fixture
def batch(session, ing_account, year2026):
    b = BankImportBatch(
        bank_account_id=ing_account.id, status="afgerond", original_filename="x.csv", sha256="0" * 64,
        ext="csv", size=1, detected_format="csv", created_at=datetime(2026, 4, 2),
    )
    session.add(b)
    session.commit()
    return b


@pytest.fixture
def make_txn(session, ing_account, batch):
    counter = iter(range(1, 1000))

    def _make(amount, desc="Betaling", name="Klant BV", iban=CUSTOMER_IBAN):
        t = BankTransaction(
            bank_account_id=ing_account.id, import_batch_id=batch.id, booking_date=PAY_DAY,
            amount_cents=amount, currency="EUR", counterparty_name=name, counterparty_iban=iban,
            description=desc, bank_reference=None, dedupe_key=f"k{next(counter)}", occurrence=1, raw="{}",
            status="nieuw", created_at=datetime(2026, 4, 2),
        )
        session.add(t)
        session.commit()
        return t

    return _make


@pytest.fixture
def klant(customer, session):
    customer.iban = CUSTOMER_IBAN
    session.commit()
    return customer


def balance(session, code):
    return {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session)}.get(code, 0)


def alloc(inv, amount=None):
    return Allocation("sales_invoice", inv.id, amount if amount is not None else inv.total_incl_cents)


def test_open_sales_invoice_is_listed_on_debtor_side_only(session, klant, make_final):
    inv = make_final(klant)
    assert inv.total_incl_cents == 12100
    assert list_open_items(session, "crediteur") == []
    (item,) = list_open_items(session, "debiteur")
    assert (item.source, item.source_id, item.number, item.open_cents, item.side, item.is_credit) == (
        "sales_invoice", inv.id, inv.number, 12100, "debiteur", False,
    )
    assert item.iban == CUSTOMER_IBAN


def test_concept_and_stornoed_invoice_are_not_open(session, klant, make_concept, make_final):
    make_concept(klant)
    assert list_open_items(session, "debiteur") == []
    inv = make_final(klant)
    from app.domain.ledger import reverse_entry

    reverse_entry(session, inv.journal_entry_id)
    session.commit()
    assert list_open_items(session, "debiteur") == []


def test_full_payment(session, klant, make_final, make_txn):
    inv = make_final(klant)
    t = make_txn(12100, f"Betaling {inv.number}")
    entry = book(session, t.id, [alloc(inv)])
    session.commit()
    assert balance(session, "1300") == 0
    assert balance(session, "1210") == 12100
    assert session.get(SalesInvoice, inv.id).paid_cents == 12100
    assert open_amount(session, inv.id) == 0
    assert get_detail(session, inv.id).status == "betaald"
    assert entry.id == session.get(BankTransaction, t.id).journal_entry_id
    assert list_open_items(session, "debiteur") == []


def test_partial_payment_then_rest(session, klant, make_final, make_txn):
    inv = make_final(klant)
    book(session, make_txn(5000).id, [alloc(inv, 5000)])
    session.commit()
    assert open_amount(session, inv.id) == 7100
    assert get_detail(session, inv.id).status in ("deels_betaald", "te_laat")
    (item,) = list_open_items(session, "debiteur")
    assert item.open_cents == 7100
    book(session, make_txn(7100).id, [alloc(inv, 7100)])
    session.commit()
    assert get_detail(session, inv.id).status == "betaald"


def test_over_allocation_refused(session, klant, make_final, make_txn):
    inv = make_final(klant)
    t = make_txn(15000)
    with pytest.raises(ReconcileError) as exc:
        book(session, t.id, [alloc(inv, 15000)])
    assert "maximaal" in exc.value.message
    assert session.get(SalesInvoice, inv.id).paid_cents == 0


def test_outgoing_payment_on_sales_invoice_refused(session, klant, make_final, make_txn):
    inv = make_final(klant)
    with pytest.raises(ReconcileError):
        book(session, make_txn(-12100).id, [alloc(inv)])


def test_mixed_sides_refused(session, klant, make_final, make_txn, acc):
    inv = make_final(klant)
    book_opening_balance(
        session,
        OpeningInput([(acc("1210"), 50000)], [OpeningItemInput("crediteur", klant.id, "OUD-9", date(2025, 12, 1), None, 4500)]),
    )
    session.commit()
    old = session.scalar(select(OpeningItem).where(OpeningItem.side == "crediteur"))
    t = make_txn(12100)
    with pytest.raises(ReconcileError) as exc:
        book(session, t.id, [alloc(inv, 8000), Allocation("opening_item", old.id, 4100)])
    assert exc.value.message == (
        "Je kunt een betaling niet tegelijk aan verkoop- en inkoopfacturen koppelen. Koppel ze apart."
    )
    assert session.get(BankTransaction, t.id).status == "nieuw"


def paid_invoice_with_open_credit(session, klant, make_final, make_txn, storage):
    inv = make_final(klant)
    book(session, make_txn(12100).id, [alloc(inv)])
    session.commit()
    note = create_credit_concept(session, inv.id, today=date(2026, 3, 15))
    session.commit()
    finalize(session, note.id, storage=storage)
    session.commit()
    return inv, note


def test_refund_of_credit_note(session, klant, make_final, make_txn, storage):
    inv, note = paid_invoice_with_open_credit(session, klant, make_final, make_txn, storage)
    assert open_amount(session, note.id) == 12100
    (item,) = list_open_items(session, "debiteur")
    assert item.is_credit and item.number == note.number and item.open_cents == 12100
    t = make_txn(-12100, f"Terugbetaling {note.number}")
    (best,) = [s for s in suggestions_for(session, t.id) if s.confidence == "zeker"]
    assert best.label == f"Verkoopcreditnota {note.number} - Klant BV"
    accept(session, t.id, best.key)
    session.commit()
    assert session.get(SalesInvoice, note.id).paid_cents == 12100
    assert open_amount(session, note.id) == 0
    # invoice 121 debit, paid 121 credit, credit note 121 credit, refund 121 debit
    assert balance(session, "1300") == 0
    assert balance(session, "1210") == 0


def test_incoming_payment_cannot_be_matched_to_credit_note_only(session, klant, make_final, make_txn, storage):
    inv, note = paid_invoice_with_open_credit(session, klant, make_final, make_txn, storage)
    with pytest.raises(ReconcileError):
        book(session, make_txn(12100).id, [alloc(note)])


def test_opening_item_of_klant_is_paid(session, klant, make_txn, acc, year2026):
    book_opening_balance(
        session,
        OpeningInput([(acc("1210"), 50000)], [OpeningItemInput("debiteur", klant.id, "OUD-1", date(2025, 12, 1), None, 4500)]),
    )
    session.commit()
    (item,) = list_open_items(session, "debiteur")
    assert (item.source, item.number, item.open_cents) == ("opening_item", "OUD-1", 4500)
    assert list_open_items(session, "crediteur") == []
    before = balance(session, "1300")
    t = make_txn(4500, "OUD-1")
    (s,) = [s for s in suggestions_for(session, t.id) if s.confidence == "zeker"]
    accept(session, t.id, s.key)
    session.commit()
    assert balance(session, "1300") == before - 4500
    assert session.scalar(select(OpeningItem.paid_cents).where(OpeningItem.side == "debiteur")) == 4500


def test_undo_restores_open_amount_and_recomputes(session, klant, make_final, make_txn):
    inv = make_final(klant)
    t1 = make_txn(5000)
    t2 = make_txn(2000)
    book(session, t1.id, [alloc(inv, 5000)])
    book(session, t2.id, [alloc(inv, 2000)])
    session.commit()
    assert open_amount(session, inv.id) == 5100
    undo(session, t1.id)
    session.commit()
    assert session.get(SalesInvoice, inv.id).paid_cents == 2000  # recomputed, not subtracted blindly
    assert open_amount(session, inv.id) == 10100
    assert get_detail(session, inv.id).status != "betaald"
    assert session.get(BankTransaction, t1.id).status == "nieuw"
    assert [m.reversed_at is not None for m in session.scalars(select(BankMatch).order_by(BankMatch.id))] == [True, False]


def test_invoice_number_in_description_gives_zeker_suggestion_and_shows_in_list(session, klant, make_final, make_txn):
    inv = make_final(klant)
    other = make_final(klant, day=DAY)
    t = make_txn(12100, f"Factuur {inv.number.replace('-', '')} bedankt")
    (best, *_) = suggestions_for(session, t.id)
    assert best.confidence == "zeker" and best.allocations[0].source_id == inv.id
    assert best.label == f"Verkoopfactuur {inv.number} - Klant BV"
    row = list_to_process(session).items[0]
    assert row.suggestion.label == best.label
    assert other.id != inv.id


def test_end_to_end_finalize_import_accept_undo(session, klant, make_final, make_txn):
    inv = make_final(klant)
    assert get_detail(session, inv.id).status in ("openstaand", "te_laat")
    t = make_txn(12100, f"Betaling {inv.number}")
    accept(session, t.id, suggestions_for(session, t.id)[0].key)
    session.commit()
    detail = get_detail(session, inv.id)
    assert detail.status == "betaald" and detail.open_cents == 0
    tx = get_transaction_detail(session, t.id)
    assert [(m.source, m.side, m.number) for m in tx.matches] == [("sales_invoice", "debiteur", inv.number)]
    undo(session, t.id)
    session.commit()
    detail = get_detail(session, inv.id)
    assert detail.open_cents == 12100 and detail.status != "betaald"


def test_paid_cents_only_changes_on_sales_invoice(session, klant, make_final, make_txn):
    """The immutability trigger of a definitief invoice allows the paid_cents update."""
    inv = make_final(klant)
    book(session, make_txn(100).id, [alloc(inv, 100)])
    session.commit()
    assert session.get(SalesInvoice, inv.id).paid_cents == 100
