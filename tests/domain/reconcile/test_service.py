"""Reconcile service on a real SQLite database: book, split, partial, undo, ignore, errors."""

from datetime import date

import pytest
from sqlalchemy import select, text

from app.domain.errors import LedgerError
from app.domain.ledger import lock_period, trial_balance
from app.domain.purchase import list_invoices, open_by_supplier
from app.domain.reconcile import (
    Allocation,
    DirectLine,
    ReconcileError,
    RuleDraft,
    accept,
    book,
    direct_defaults,
    get_transaction_detail,
    ignore,
    list_open_items,
    list_rules,
    list_to_process,
    restore,
    suggestions_for,
    to_process_count,
    undo,
)
from app.models import BankMatch, BankTransaction, JournalEntry, OpeningItem, Period, PurchaseInvoice


def balance(session, code):
    return {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session)}.get(code, 0)


def inv(pi):
    return Allocation("purchase_invoice", pi.id, pi.total_incl_cents)


def test_pay_invoice_full(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn(-12100, "Betaling F-1")
    entry = book(session, t.id, [inv(pi)])
    session.commit()

    assert balance(session, "3000") == 0  # booked +121 credit, paid -121
    assert balance(session, "1210") == -12100
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 12100
    t = session.get(BankTransaction, t.id)
    assert (t.status, t.journal_entry_id) == ("geboekt", entry.id)
    assert entry.booking_date == date(2025, 4, 1) and entry.reference == "F-1"
    matches = session.scalars(select(BankMatch)).all()
    assert [(m.amount_cents, m.reversed_at) for m in matches] == [(12100, None)]
    assert to_process_count(session) == 0
    # /inkoop and crediteuren reflect it with no changes to their code
    assert list_invoices(session).items[0].status == "betaald"
    assert open_by_supplier(session).total_open_cents == 0


def test_entry_is_in_the_bank_dagboek(session, invoice, make_txn, ing_account):
    pi, _ = invoice()
    entry = book(session, make_txn().id, [inv(pi)])
    assert entry.journal_id == ing_account.journal_id


def test_partial_payment_keeps_invoice_open(session, invoice, make_txn):
    pi, _ = invoice()
    book(session, make_txn(-5000).id, [Allocation("purchase_invoice", pi.id, 5000)])
    session.commit()
    row = list_invoices(session).items[0]
    assert (row.status, row.open_cents) == ("open", 7100)
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 5000
    # the rest can be paid by a second transaction
    book(session, make_txn(-7100).id, [Allocation("purchase_invoice", pi.id, 7100)])
    session.commit()
    assert list_invoices(session).items[0].status == "betaald"


def test_over_allocation_refused(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn(-20000)
    with pytest.raises(ReconcileError) as exc:
        book(session, t.id, [Allocation("purchase_invoice", pi.id, 20000)])
    assert exc.value.message == "Je kunt maximaal € 121,00 aan deze factuur toewijzen; er staat nog € 121,00 open."
    assert session.get(BankTransaction, t.id).status == "nieuw"


def test_remainder_must_be_zero(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn(-13000)
    with pytest.raises(ReconcileError) as exc:
        book(session, t.id, [inv(pi)])
    assert exc.value.message == "Er is nog € 9,00 niet verdeeld."
    assert session.scalars(select(BankMatch)).all() == []


def test_split_over_two_invoices_and_credit_note(session, invoice, make_txn, make_supplier):
    a, supplier = invoice("F-1")
    b, _ = invoice("F-2", contact=supplier)
    c, _ = invoice("C-1", contact=supplier, kind="credit_note", lines=[("Retour", 1000, 210, "NL_21", "4200")])
    t = make_txn(-(12100 + 12100 - 1210))
    entry = book(
        session, t.id,
        [inv(a), inv(b), Allocation("purchase_invoice", c.id, 1210)],
    )
    session.commit()
    lines = [(l.account_id, l.debit_cents, l.credit_cents) for l in entry.lines]
    assert len(lines) == 4  # three 3000 lines (one per allocation) + bank
    assert sum(d for _, d, _ in lines) == sum(c_ for _, _, c_ in lines) == 24200
    assert session.get(PurchaseInvoice, c.id).paid_cents == 1210
    assert open_by_supplier(session).total_open_cents == 0
    assert len(session.scalars(select(BankMatch)).all()) == 3


def test_credit_note_refund(session, invoice, make_txn):
    c, _ = invoice("C-9", kind="credit_note", lines=[("Retour", 5000, 1050, "NL_21", "4200")])
    t = make_txn(6050, "Terugbetaling C-9")
    entry = book(session, t.id, [Allocation("purchase_invoice", c.id, 6050)])
    session.commit()
    bank = [l for l in entry.lines if l.debit_cents == 6050]
    assert len(bank) == 1
    assert session.get(PurchaseInvoice, c.id).paid_cents == 6050
    assert balance(session, "3000") == 0


def test_credit_note_with_money_going_out_refused(session, invoice, make_txn):
    c, _ = invoice("C-9", kind="credit_note", lines=[("Retour", 5000, 1050, "NL_21", "4200")])
    with pytest.raises(ReconcileError) as exc:
        book(session, make_txn(-6050).id, [Allocation("purchase_invoice", c.id, 6050)])
    assert "alleen koppelen aan inkoopfacturen" in exc.value.message


def test_opening_item_payment(session, opening_item, make_txn):
    item, _ = opening_item
    book(session, make_txn(-4500, "OUD-1").id, [Allocation("opening_item", item.id, 4500)])
    session.commit()
    assert session.get(OpeningItem, item.id).paid_cents == 4500
    assert open_by_supplier(session).total_open_cents == 0


def test_open_items_listing(session, invoice, opening_item):
    pi, supplier = invoice()
    items = list_open_items(session, "crediteur")
    assert {(i.source, i.number, i.open_cents, i.is_credit) for i in items} == {
        ("purchase_invoice", "F-1", 12100, False), ("opening_item", "OUD-1", 4500, False),
    }
    assert [i.number for i in list_open_items(session, contact_id=supplier.id)] == ["F-1"]
    assert [i.number for i in list_open_items(session, q="plaza")] == ["OUD-1"]
    assert list_open_items(session, "debiteur") == []


def test_storno_d_invoice_not_offered(session, invoice):
    from app.domain.ledger import reverse_entry

    pi, _ = invoice()
    reverse_entry(session, pi.journal_entry_id)
    session.commit()
    assert list_open_items(session) == []


def test_direct_booking_with_vat(session, make_txn, acc, year2025):
    t = make_txn(-12100, "Papier", iban=None, name="Staples")
    entry = book(session, t.id, [], [DirectLine(acc("4200"), 12100, "NL_21", "Papier")])
    session.commit()
    assert balance(session, "1400") == 2100
    assert balance(session, "4200") == 10000
    assert balance(session, "1210") == -12100
    detail = get_transaction_detail(session, t.id)
    assert detail.is_direct_booked and detail.can_undo and detail.matches == []
    assert detail.journal_entry_number == entry.entry_number


def test_direct_booking_defaults_vat_from_account(session, make_txn, acc, year2025):
    from app.domain.ledger import set_account_vat_default

    set_account_vat_default(session, acc("4200"), "NL_21")
    session.commit()
    t = make_txn(-12100, iban=None)
    book(session, t.id, [], [DirectLine(acc("4200"), 12100, None)])
    assert balance(session, "1400") == 2100


def test_direct_booking_without_vat_code_or_default_refused(session, make_txn, acc, year2025):
    from app.domain.ledger import set_account_vat_default

    set_account_vat_default(session, acc("4200"), None)
    session.commit()
    t = make_txn(-100, iban=None)
    with pytest.raises(ReconcileError):
        book(session, t.id, [], [DirectLine(acc("4200"), 100, None)])


def test_direct_booking_unsupported_vat(session, make_txn, acc, year2025):
    t = make_txn(-100, iban=None)
    with pytest.raises(ReconcileError):
        book(session, t.id, [], [DirectLine(acc("4200"), 100, "EU_GOEDEREN")])


def test_direct_bij_without_vat(session, make_txn, acc, year2025):
    t = make_txn(250, "Rente", iban=None)
    book(session, t.id, [], [DirectLine(acc("8000"), 250, "GEEN")])
    session.commit()
    assert balance(session, "1210") == 250 and balance(session, "8000") == -250


def test_combined_invoice_and_bank_costs(session, invoice, make_txn, acc):
    pi, _ = invoice()
    t = make_txn(-12100 - 250, "F-1 + kosten")
    book(session, t.id, [inv(pi)], [DirectLine(acc("4200"), 250, "GEEN", "Bankkosten")])
    session.commit()
    assert balance(session, "1210") == -12350
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 12100


def test_double_booking_yields_one_entry(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn()
    book(session, t.id, [inv(pi)])
    session.commit()
    before = len(session.scalars(select(JournalEntry)).all())
    with pytest.raises(ReconcileError) as exc:
        book(session, t.id, [inv(pi)])
    assert exc.value.message == "Deze mutatie is al verwerkt."
    assert len(session.scalars(select(JournalEntry)).all()) == before
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 12100


def test_failed_booking_leaves_nothing_behind(session, invoice, make_txn, year2025):
    pi, _ = invoice()
    t = make_txn(-12100, day=date(2026, 6, 1))  # no boekjaar for 2026
    with pytest.raises(LedgerError):
        book(session, t.id, [inv(pi)])
    session.commit()
    assert session.get(BankTransaction, t.id).status == "nieuw"
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 0
    assert session.scalars(select(BankMatch)).all() == []


def test_locked_period_refused_with_plain_message(session, invoice, make_txn):
    pi, _ = invoice()
    period = session.scalar(select(Period).where(Period.start_date <= date(2025, 4, 1), Period.end_date >= date(2025, 4, 1)))
    lock_period(session, period.id)
    session.commit()
    t = make_txn()
    with pytest.raises(LedgerError) as exc:
        book(session, t.id, [inv(pi)])
    assert "vergrendeld" in exc.value.message
    assert session.get(BankTransaction, t.id).status == "nieuw"


def test_duplicate_item_in_allocations_refused(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn(-12100)
    with pytest.raises(ReconcileError):
        book(session, t.id, [Allocation("purchase_invoice", pi.id, 6000), Allocation("purchase_invoice", pi.id, 6100)])


def test_already_paid_item_cannot_be_allocated(session, invoice, make_txn):
    pi, _ = invoice()
    book(session, make_txn().id, [inv(pi)])
    session.commit()
    with pytest.raises(ReconcileError) as exc:
        book(session, make_txn().id, [inv(pi)])
    assert "niet meer open" in exc.value.message


# --- undo ------------------------------------------------------------------------------------------
def test_undo_restores_everything(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn()
    entry = book(session, t.id, [inv(pi)])
    session.commit()
    storno = undo(session, t.id)
    session.commit()

    assert storno.kind == "storno" and storno.reverses_entry_id == entry.id
    t = session.get(BankTransaction, t.id)
    assert (t.status, t.journal_entry_id) == ("nieuw", None)
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 0
    match = session.scalars(select(BankMatch)).one()
    assert match.reversed_at is not None
    assert balance(session, "3000") == -12100 and balance(session, "1210") == 0
    assert list_invoices(session).items[0].status == "open"
    # and the transaction can be booked again
    book(session, t.id, [inv(pi)])
    session.commit()
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 12100
    assert len(session.scalars(select(BankMatch)).all()) == 2


def test_undo_recomputes_paid_from_remaining_matches(session, invoice, make_txn):
    pi, _ = invoice()
    t1 = make_txn(-5000)
    t2 = make_txn(-7100)
    book(session, t1.id, [Allocation("purchase_invoice", pi.id, 5000)])
    book(session, t2.id, [Allocation("purchase_invoice", pi.id, 7100)])
    session.commit()
    undo(session, t1.id)
    session.commit()
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 7100


def test_undo_direct_booking(session, make_txn, acc, year2025):
    t = make_txn(-1000, iban=None)
    book(session, t.id, [], [DirectLine(acc("4200"), 1000, "GEEN")])
    session.commit()
    undo(session, t.id)
    session.commit()
    assert session.get(BankTransaction, t.id).status == "nieuw"
    assert balance(session, "1210") == 0


def test_undo_unbooked_refused(session, make_txn):
    with pytest.raises(ReconcileError):
        undo(session, make_txn().id)


def test_undo_twice_refused(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn()
    book(session, t.id, [inv(pi)])
    session.commit()
    undo(session, t.id)
    session.commit()
    with pytest.raises(ReconcileError):
        undo(session, t.id)


def test_undo_in_locked_period_refused(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn()
    book(session, t.id, [inv(pi)])
    session.commit()
    period = session.scalar(select(Period).where(Period.start_date <= date(2025, 4, 1), Period.end_date >= date(2025, 4, 1)))
    lock_period(session, period.id)
    session.commit()
    with pytest.raises(LedgerError):
        undo(session, t.id)
    session.rollback()
    assert session.get(BankTransaction, t.id).status == "geboekt"
    assert session.get(PurchaseInvoice, pi.id).paid_cents == 12100


# --- ignore / restore ------------------------------------------------------------------------------
def test_ignore_and_restore(session, make_txn):
    t = make_txn()
    ignore(session, t.id)
    session.commit()
    assert session.get(BankTransaction, t.id).status == "genegeerd"
    assert to_process_count(session) == 0
    assert [r.id for r in list_to_process(session, status="genegeerd").items] == [t.id]
    with pytest.raises(ReconcileError):
        book(session, t.id, [], [])
    restore(session, t.id)
    session.commit()
    assert session.get(BankTransaction, t.id).status == "nieuw"
    with pytest.raises(ReconcileError):
        restore(session, t.id)


def test_cannot_ignore_booked(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn()
    book(session, t.id, [inv(pi)])
    with pytest.raises(ReconcileError) as exc:
        ignore(session, t.id)
    assert exc.value.message == "Deze mutatie is al verwerkt."


# --- suggestions / accept ----------------------------------------------------------------------------
def test_suggestion_and_accept(session, invoice, make_txn):
    pi, _ = invoice()
    t = make_txn(-12100, "Betaling factuur F1")
    sug = suggestions_for(session, t.id)
    assert sug[0].confidence == "zeker" and sug[0].allocations[0].source_id == pi.id
    entry = accept(session, t.id, sug[0].key)
    session.commit()
    assert entry.id and session.get(PurchaseInvoice, pi.id).paid_cents == 12100
    assert suggestions_for(session, t.id) == []


def test_accept_unknown_key_refused(session, invoice, make_txn):
    invoice()
    t = make_txn()
    with pytest.raises(ReconcileError):
        accept(session, t.id, "match:purchase_invoice-99-1")


def test_accept_twice_second_fails(session, invoice, make_txn):
    invoice()
    t = make_txn()
    key = suggestions_for(session, t.id)[0].key
    accept(session, t.id, key)
    session.commit()
    with pytest.raises(ReconcileError) as exc:
        accept(session, t.id, key)
    assert exc.value.message == "Deze mutatie is al verwerkt."


def test_list_to_process_shows_best_suggestion_and_filters(session, invoice, make_txn):
    invoice()
    make_txn(-12100, "F1", day=date(2025, 4, 3))
    make_txn(500, "Rente", iban=None, name="ING", day=date(2025, 4, 5))
    page = list_to_process(session)
    assert [r.description for r in page.items] == ["Rente", "F1"]  # newest first
    assert page.items[0].suggestion is None and page.items[1].suggestion.confidence == "zeker"
    assert [r.description for r in list_to_process(session, direction="af").items] == ["F1"]
    assert [r.description for r in list_to_process(session, q="rente").items] == ["Rente"]
    assert page.total == 2


# --- rules -----------------------------------------------------------------------------------------------------
def test_remember_rule_creates_rule_then_suggests_it(session, make_txn, acc, year2025):
    t = make_txn(-1500, "Abonnement mei", iban="NL20INGB0001234567", name="Telecom")
    book(session, t.id, [], [DirectLine(acc("4200"), 1500, "NL_21", "Abonnement")],
         remember_rule=RuleDraft(use_iban=True, description_contains="abonnement"))
    session.commit()
    rules = list_rules(session)
    assert len(rules) == 1 and rules[0].use_count == 1 and rules[0].account_code == "4200"
    assert rules[0].counterparty_iban == "NL20INGB0001234567" and rules[0].direction == "af"

    t2 = make_txn(-1650, "Abonnement juni", iban="NL20INGB0001234567", name="Telecom")
    s = suggestions_for(session, t2.id)
    assert s[0].kind == "rule" and s[0].confidence == "zeker"
    assert s[0].direct_lines[0].amount_cents == 1650
    accept(session, t2.id, s[0].key)
    session.commit()
    assert list_rules(session)[0].use_count == 2
    assert balance(session, "4200") == 1240 + 1364


def test_remember_rule_requires_a_condition(session, make_txn, acc, year2025):
    t = make_txn(-1500, "x", iban=None)
    with pytest.raises(ReconcileError):
        book(session, t.id, [], [DirectLine(acc("4200"), 1500, "GEEN")], remember_rule=RuleDraft())
    assert session.get(BankTransaction, t.id).status == "nieuw"


def test_remember_rule_without_direct_line_refused(session, invoice, make_txn):
    pi, _ = invoice()
    with pytest.raises(ReconcileError):
        book(session, make_txn().id, [inv(pi)], remember_rule=RuleDraft())


def test_identical_rule_is_reused(session, make_txn, acc, year2025):
    for _ in range(2):
        t = make_txn(-1500, "Abonnement", iban="NL20INGB0001234567")
        book(session, t.id, [], [DirectLine(acc("4200"), 1500, "GEEN")], remember_rule=RuleDraft())
    assert len(list_rules(session)) == 1 and list_rules(session)[0].use_count == 2


def test_direct_defaults_from_rule_then_last_used(session, make_txn, acc, year2025):
    iban = "NL20INGB0001234567"
    assert direct_defaults(session, make_txn(-100, iban=iban).id) is None
    first = make_txn(-2000, "x", iban=iban)
    book(session, first.id, [], [DirectLine(acc("4200"), 2000, "NL_9")])
    session.commit()
    d = direct_defaults(session, make_txn(-300, iban=iban).id)
    assert (d.account_id, d.vat_code, d.amount_cents) == (acc("4200"), "NL_9", 300)


def test_detail_default_contact_from_iban(session, invoice, make_txn):
    pi, supplier = invoice()
    detail = get_transaction_detail(session, make_txn().id)
    assert detail.default_contact_id == supplier.id and detail.status == "nieuw"


# --- append-only ------------------------------------------------------------------------------------------------
def test_bank_match_is_append_only(session, invoice, make_txn):
    pi, _ = invoice()
    book(session, make_txn().id, [inv(pi)])
    session.commit()
    with pytest.raises(Exception, match="onveranderlijk"):
        session.execute(text("DELETE FROM bank_match"))
    session.rollback()
    with pytest.raises(Exception, match="onveranderlijk"):
        session.execute(text("UPDATE bank_match SET amount_cents = 1"))
    session.rollback()
