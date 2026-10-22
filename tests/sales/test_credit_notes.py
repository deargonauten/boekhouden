from datetime import date

import pytest
from sqlalchemy import select

from app.domain.ledger import reverse_entry, trial_balance
from app.domain.sales import (
    ConceptInput,
    LineInput,
    SalesError,
    build_document,
    create_credit_concept,
    finalize,
    get_detail,
    open_amount,
    save_concept,
)
from app.models import JournalLine, SalesCreditApplication

DAY = date(2026, 3, 10)


def credit_lines(note, qty_by_position):
    return [
        LineInput(l.description, qty_by_position.get(i, l.quantity_milli), l.unit_price_cents, l.vat_code,
                  l.account_id, l.unit, l.original_line_id)
        for i, l in enumerate(note.lines)
        if i in qty_by_position or not qty_by_position
    ]


@pytest.fixture
def original(make_final, customer, acc):
    return make_final(
        customer,
        lines=[
            LineInput("Website", 3000, 10000, "NL_21", acc("8000")),
            LineInput("Boek", 1000, 5000, "NL_9", acc("8010")),
        ],
    )


def test_credit_concept_is_prefilled_from_original(session, original):
    note = create_credit_concept(session, original.id, today=date(2026, 3, 15))
    session.commit()
    assert note.kind == "credit_note" and note.status == "concept" and note.number is None
    assert note.credited_invoice_id == original.id
    assert note.due_date == note.invoice_date == date(2026, 3, 15)
    assert [(l.description, l.quantity_milli, l.unit_price_cents, l.vat_code) for l in note.lines] == [
        ("Website", 3000, 10000, "NL_21"), ("Boek", 1000, 5000, "NL_9")]
    assert [l.original_line_id for l in note.lines] == [l.id for l in original.lines]
    assert note.total_incl_cents == original.total_incl_cents


def test_credit_note_finalize_entry_numbering_and_settlement(session, original, storage, acc):
    note = create_credit_concept(session, original.id, today=date(2026, 3, 15))
    session.commit()
    save_concept(session, note.id, ConceptInput(note.contact_id, note.invoice_date, credit_lines(note, {0: 1000})))
    finalize(session, note.id, storage=storage)
    session.commit()
    assert note.number == "2026-0002"  # shared series with invoices
    lines = {l.account_id: l for l in session.scalars(select(JournalLine).where(JournalLine.entry_id == note.journal_entry_id))}
    assert lines[acc("1300")].credit_cents == 12100 and lines[acc("1300")].debit_cents == 0
    assert lines[acc("8000")].debit_cents == 10000 and lines[acc("3100")].debit_cents == 2100
    app = session.scalars(select(SalesCreditApplication)).one()
    assert (app.credit_note_id, app.invoice_id, app.amount_cents) == (note.id, original.id, 12100)
    total = original.total_incl_cents
    assert open_amount(session, original) == total - 12100
    assert open_amount(session, note) == 0  # fully set off
    d_orig = get_detail(session, original.id, today=date(2026, 3, 20))
    d_note = get_detail(session, note.id, today=date(2026, 3, 20))
    assert d_orig.applied_cents == 12100 and d_orig.status == "deels_betaald"
    assert d_note.status == "verrekend"
    assert d_orig.credit_notes[0].id == note.id and d_note.original.id == original.id
    assert d_orig.can_credit


def test_credit_note_pdf_snapshot_references_original(session, original, storage):
    note = create_credit_concept(session, original.id)
    finalize(session, note.id, storage=storage)
    doc = build_document(session, note.id)
    assert doc.kind == "credit_note" and doc.credited_number == original.number
    assert doc.credited_date == original.invoice_date and doc.total_incl_cents > 0


def test_full_credit_makes_invoice_gecrediteerd_and_blocks_more(session, original, storage):
    note = create_credit_concept(session, original.id)
    finalize(session, note.id, storage=storage)
    session.commit()
    assert open_amount(session, original) == 0
    assert get_detail(session, original.id).status == "gecrediteerd"
    assert not get_detail(session, original.id).can_credit
    with pytest.raises(SalesError) as exc:
        create_credit_concept(session, original.id)
    assert "al helemaal gecrediteerd" in exc.value.message


def test_over_credit_refused(session, original, storage):
    first = create_credit_concept(session, original.id)
    save_concept(session, first.id, ConceptInput(first.contact_id, first.invoice_date, credit_lines(first, {0: 2000})))
    second = create_credit_concept(session, original.id)  # both concepts, 3 left each
    session.commit()
    finalize(session, first.id, storage=storage)
    session.commit()
    with pytest.raises(SalesError) as exc:  # second still asks for 3 but only 1 is left
        finalize(session, second.id, storage=storage)
    assert exc.value.code == "OVER_CREDIT"
    assert exc.value.message == "Je kunt maximaal 1 van deze regel crediteren; er is al 2 gecrediteerd."
    session.rollback()
    with pytest.raises(SalesError):
        save_concept(session, second.id, ConceptInput(second.contact_id, second.invoice_date, credit_lines(second, {0: 1500})))


def test_credit_note_cannot_add_lines_or_change_price(session, original):
    note = create_credit_concept(session, original.id)
    with pytest.raises(SalesError) as exc:
        save_concept(session, note.id, ConceptInput(note.contact_id, note.invoice_date,
                                                    [LineInput("Extra", 1000, 100, "NL_21", None)]))
    assert exc.value.code == "CREDIT_LINES_FIXED"
    assert exc.value.message == (
        "Een creditnota corrigeert alleen de oorspronkelijke factuur. "
        "Wil je iets anders aanrekenen, maak dan een nieuwe factuur."
    )
    lines = credit_lines(note, {0: 1000})
    lines[0] = LineInput("Anders", 1000, 1, "NL_0", None, "stuk", lines[0].original_line_id)  # price/vat ignored
    save_concept(session, note.id, ConceptInput(note.contact_id, note.invoice_date, lines))
    assert (note.lines[0].description, note.lines[0].unit_price_cents, note.lines[0].vat_code) == ("Website", 10000, "NL_21")


def test_no_credit_for_credit_note_concept_or_stornoed(session, original, make_concept, customer, storage):
    concept = make_concept(customer)
    with pytest.raises(SalesError):
        create_credit_concept(session, concept.id)
    note = create_credit_concept(session, original.id)
    finalize(session, note.id, storage=storage)
    with pytest.raises(SalesError):
        create_credit_concept(session, note.id)
    reverse_entry(session, original.journal_entry_id)
    with pytest.raises(SalesError):
        create_credit_concept(session, original.id)


def test_credit_more_than_open_leaves_remaining_credit(session, original, storage):
    original.paid_cents = original.total_incl_cents - 2000  # 20,00 still open
    session.commit()
    note = create_credit_concept(session, original.id)
    finalize(session, note.id, storage=storage)
    session.commit()
    app = session.scalars(select(SalesCreditApplication)).one()
    assert app.amount_cents == 2000
    assert open_amount(session, original) == 0
    assert open_amount(session, note) == note.total_incl_cents - 2000  # you owe this back
    assert get_detail(session, original.id, today=date(2026, 3, 20)).status == "betaald"
    note.paid_cents = 1000  # refunded by bank 'af' matches
    session.commit()
    assert open_amount(session, note) == note.total_incl_cents - 3000


def test_trial_balance_after_credit(session, original, storage):
    note = create_credit_concept(session, original.id)
    finalize(session, note.id, storage=storage)
    session.commit()
    tb = {r.code: r for r in trial_balance(session)}
    assert tb["1300"].debit_cents == tb["1300"].credit_cents
    assert tb["3100"].debit_cents == tb["3100"].credit_cents
    assert tb["8000"].debit_cents == tb["8000"].credit_cents


def _credit(session, storage, original, qty_milli):
    note = create_credit_concept(session, original.id, today=date(2026, 3, 15))
    session.commit()
    save_concept(session, note.id, ConceptInput(note.contact_id, note.invoice_date, credit_lines(note, {0: qty_milli})))
    finalize(session, note.id, storage=storage)
    session.commit()
    return note


@pytest.mark.parametrize("vat_code", ["NL_0", "NL_21"])
def test_partial_credits_never_exceed_the_original_amounts(session, make_final, customer, acc, storage, vat_code):
    original = make_final(customer, lines=[LineInput("Klus", 1000, 101, vat_code, acc("8000"))])
    notes = [_credit(session, storage, original, 500), _credit(session, storage, original, 500)]
    assert sum(n.total_excl_cents for n in notes) == original.total_excl_cents == 101
    assert sum(n.total_vat_cents for n in notes) == original.total_vat_cents
    assert sum(n.total_incl_cents for n in notes) == original.total_incl_cents
    assert [n.lines[0].line_excl_cents for n in notes] == [51, 50]  # last credit takes the remainder
    assert open_amount(session, original) == 0 and open_amount(session, notes[1]) == 0
    tb = {r.code: r for r in trial_balance(session)}
    assert tb["1300"].debit_cents == tb["1300"].credit_cents


def test_three_thirds_stay_within_original(session, make_final, customer, acc, storage):
    original = make_final(customer, lines=[LineInput("Klus", 1000, 101, "NL_21", acc("8000"))])
    notes = [_credit(session, storage, original, 333) for _ in range(3)]
    assert sum(n.total_excl_cents for n in notes) <= original.total_excl_cents
    assert sum(n.total_vat_cents for n in notes) <= original.total_vat_cents
    assert sum(n.total_incl_cents for n in notes) <= original.total_incl_cents
    assert all(n.total_incl_cents >= 0 for n in notes)
    assert open_amount(session, original) >= 0


def test_reversed_original_releases_credit_application(session, original, storage, acc):
    from app.domain.reconcile import list_open_items
    from app.domain.sales import debiteuren_overview, stats

    note = create_credit_concept(session, original.id)
    finalize(session, note.id, storage=storage)
    session.commit()
    assert stats(session, date(2026, 3, 20)).total_open_cents == 0
    reverse_entry(session, original.journal_entry_id)
    session.commit()

    tb = {r.code: r for r in trial_balance(session)}
    balance_1300 = tb["1300"].debit_cents - tb["1300"].credit_cents  # negative: we owe the klant
    assert balance_1300 == -original.total_incl_cents
    assert open_amount(session, original) == 0
    assert open_amount(session, note) == note.total_incl_cents  # the credit is open again
    assert get_detail(session, note.id, today=date(2026, 3, 20)).status == "openstaand"
    assert stats(session, date(2026, 3, 20)).total_open_cents == balance_1300
    rows = debiteuren_overview(session, date(2026, 3, 20))
    assert sum(r.total_cents for r in rows) == balance_1300
    items = [i for i in list_open_items(session, "debiteur") if i.source == "sales_invoice"]
    assert [(i.source_id, i.open_cents, i.is_credit) for i in items] == [(note.id, note.total_incl_cents, True)]
