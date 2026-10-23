"""book_extraction / prepare_booking on a migrated sqlite database."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.domain.errors import DocumentNotFoundError, LedgerError
from app.domain.ledger import get_entry, lock_period, reverse_entry, trial_balance
from app.domain.purchase import (
    BookingError,
    BookingPreview,
    book_extraction,
    find_invoice_for_document,
    find_invoice_for_entry,
    prepare_booking,
)
from app.domain.purchase import service as purchase_service
from app.domain.purchase.errors import (
    ALREADY_BOOKED,
    DUPLICATE_INVOICE,
    NO_JOURNAL,
    NOT_REVIEWED,
)
from app.models import (
    Document,
    EntrySequence,
    Journal,
    JournalEntry,
    Period,
    PurchaseInvoice,
    SupplierDefault,
)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def balance(session, code):
    """debit - credit on an account."""
    for row in trial_balance(session):
        if row.code == code:
            return row.debit_cents - row.credit_cents
    return 0


# --- happy path ----------------------------------------------------------------------------
def test_book_creates_entry_invoice_and_links_document(session, year2025, make_extraction, acc):
    doc = make_extraction(due_date=date(2025, 4, 9))
    invoice = book_extraction(session, doc.id)
    session.commit()

    assert isinstance(invoice, PurchaseInvoice)
    assert invoice.document_id == doc.id
    assert invoice.invoice_number == "F-1" and invoice.invoice_number_key == "f-1"
    assert invoice.invoice_date == date(2025, 3, 10)
    assert invoice.due_date == date(2025, 4, 9)
    assert invoice.kind == "invoice"
    assert (invoice.total_excl_cents, invoice.total_vat_cents, invoice.total_incl_cents) == (10000, 2100, 12100)
    assert invoice.paid_cents == 0

    entry = session.get(JournalEntry, invoice.journal_entry_id)
    assert entry.entry_number == "IK-2025-0001"
    assert entry.booking_date == date(2025, 3, 10)
    assert entry.reference == "F-1"
    assert entry.description == "Bol B.V. - F-1"
    assert entry.source_type == "inkoopfactuur"
    assert entry.source_id == invoice.id

    detail = get_entry(session, entry.id)
    assert [(l.account_code, l.debit_cents, l.credit_cents, l.vat_code) for l in detail.lines] == [
        ("4625", 10000, 0, "NL_21"),
        ("1400", 2100, 0, None),
        ("3000", 0, 12100, None),
    ]

    session.refresh(doc)
    assert doc.status == "geboekt"
    assert doc.journal_entry_id == entry.id

    assert find_invoice_for_document(session, doc.id).id == invoice.id
    assert find_invoice_for_entry(session, entry.id).id == invoice.id
    assert find_invoice_for_entry(session, 99999) is None


def test_book_records_learned_default(session, year2025, make_extraction, acc):
    doc = make_extraction()
    invoice = book_extraction(session, doc.id)
    session.commit()
    row = session.scalar(select(SupplierDefault))
    assert (row.contact_id, row.account_id, row.vat_code, row.use_count) == (
        invoice.contact_id,
        acc("4625"),
        "NL_21",
        1,
    )


def test_credit_note(session, year2025, make_extraction):
    doc = make_extraction(kind="credit_note", number="CN-1")
    invoice = book_extraction(session, doc.id)
    session.commit()
    assert invoice.kind == "credit_note"
    assert invoice.total_incl_cents == 12100
    assert balance(session, "3000") == 12100  # debit: you are owed money
    assert balance(session, "1400") == -2100
    assert balance(session, "4625") == -10000


def test_receipt_is_booked_as_invoice(session, year2025, make_extraction):
    doc = make_extraction(kind="receipt")
    assert book_extraction(session, doc.id).kind == "invoice"


def test_trial_balance_matches_open_invoices(session, year2025, make_extraction, make_supplier):
    other = make_supplier("Kantoor B.V.")
    book_extraction(session, make_extraction(number="A1").id)
    book_extraction(
        session,
        make_extraction(
            contact=other,
            number="B1",
            lines=[("Stoel", 20000, 4200, "NL_21", "4625"), ("Boek", 5000, 450, "NL_9", "4635")],
        ).id,
    )
    cn = book_extraction(session, make_extraction(contact=other, number="B2", kind="credit_note").id)
    storno_me = book_extraction(session, make_extraction(number="A2").id)
    reverse_entry(session, storno_me.journal_entry_id)
    session.commit()

    open_total = sum(
        (-i.total_incl_cents if i.kind == "credit_note" else i.total_incl_cents)
        for i in session.scalars(select(PurchaseInvoice))
        if i.id != storno_me.id
    )
    assert open_total == 12100 + 29650 - 12100
    assert -balance(session, "3000") == open_total
    assert balance(session, "1400") == 2100 + 4650 - 2100
    assert cn.kind == "credit_note"


# --- refusals: nothing persisted ------------------------------------------------------------
def assert_nothing_booked(session, doc):
    session.rollback()
    assert count(session, JournalEntry) == 0
    assert count(session, PurchaseInvoice) == 0
    assert count(session, SupplierDefault) == 0
    assert session.get(Document, doc.id).status == "herkend"


def test_locked_period_rolls_back_and_keeps_sequence(session, year2025, make_extraction):
    doc = make_extraction()
    period = session.scalar(select(Period).where(Period.number == 3))
    lock_period(session, period.id)
    session.commit()
    with pytest.raises(LedgerError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == "PERIOD_LOCKED"
    assert "vergrendeld" in exc.value.message
    assert_nothing_booked(session, doc)
    assert count(session, EntrySequence) == 0


def test_no_fiscal_year(session, make_extraction):
    doc = make_extraction()
    with pytest.raises(LedgerError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == "NO_OPEN_PERIOD"
    assert_nothing_booked(session, doc)


def test_failure_after_posting_rolls_back_everything(session, year2025, make_extraction, monkeypatch):
    doc = make_extraction()

    def boom(*a, **kw):
        raise LedgerError("BOOM", "Er ging iets mis.")

    monkeypatch.setattr(purchase_service, "mark_booked", boom)
    with pytest.raises(LedgerError):
        book_extraction(session, doc.id)
    # even when the caller commits, the savepoint was rolled back
    session.commit()
    assert count(session, JournalEntry) == 0
    assert count(session, PurchaseInvoice) == 0
    assert session.get(Document, doc.id).status == "herkend"
    seq = session.scalar(select(EntrySequence.last_number))
    assert seq in (None, 0)
    monkeypatch.undo()
    invoice = book_extraction(session, doc.id)
    session.commit()
    assert session.get(JournalEntry, invoice.journal_entry_id).entry_number == "IK-2025-0001"


def test_not_reviewed(session, year2025, make_extraction):
    doc = make_extraction(reviewed=False)
    with pytest.raises(BookingError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == NOT_REVIEWED
    assert_nothing_booked(session, doc)


def test_document_without_extraction(session, year2025, make_doc):
    doc = make_doc()
    with pytest.raises(BookingError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == NOT_REVIEWED


def test_unknown_document(session, year2025):
    with pytest.raises(DocumentNotFoundError):
        book_extraction(session, 4242)
    with pytest.raises(DocumentNotFoundError):
        prepare_booking(session, 4242)


def test_eu_service_invoice_books_verlegde_btw(session, year2025, make_extraction):
    doc = make_extraction(lines=[("Hosting", 10000, 0, "EU_DIENSTEN", "4625")])
    invoice = book_extraction(session, doc.id)
    session.commit()
    assert invoice.currency == "EUR" and invoice.exchange_rate_micro is None
    assert (invoice.total_excl_cents, invoice.total_vat_cents, invoice.total_incl_cents) == (10000, 0, 10000)
    assert balance(session, "4625") == 10000
    assert balance(session, "1410") == 2100
    assert balance(session, "3130") == -2100
    assert balance(session, "3000") == -10000
    assert balance(session, "1400") == 0


def test_foreign_currency_invoice_is_booked_in_euro_and_keeps_original(session, year2025, make_extraction):
    doc = make_extraction(
        lines=[("Hosting", 10000, 0, "EU_DIENSTEN", "4625")], currency="USD", exchange_rate_micro=1_250_000,
    )
    invoice = book_extraction(session, doc.id)
    session.commit()
    assert invoice.currency == "USD"
    assert invoice.exchange_rate_micro == 1_250_000
    assert invoice.original_total_incl_cents == 10000
    assert invoice.total_incl_cents == 8000
    assert balance(session, "3000") == -8000
    assert balance(session, "3130") == -1680


def test_foreign_currency_without_rate_is_refused(session, year2025, make_extraction):
    doc = make_extraction(currency="USD")
    with pytest.raises(BookingError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == "MISSING_FIELD" and exc.value.field == "exchange_rate"
    assert_nothing_booked(session, doc)


def test_shifted_vat_rate_is_taken_from_the_review(session, year2025, make_extraction):
    doc = make_extraction(lines=[("Boek", 10000, 0, "EU_GOEDEREN", "4625")], shifted_vat_rate_bp=900)
    book_extraction(session, doc.id)
    session.commit()
    assert balance(session, "3130") == -900


def test_inactive_account_uses_ledger_message(session, year2025, make_extraction, acc):
    from app.domain.ledger import set_account_active

    doc = make_extraction()
    set_account_active(session, acc("4625"), False)
    session.commit()
    with pytest.raises(LedgerError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == "ACCOUNT_INACTIVE"
    assert_nothing_booked(session, doc)


def test_no_active_purchase_journal(session, year2025, make_extraction):
    doc = make_extraction()
    for j in session.scalars(select(Journal).where(Journal.type == "inkoop")):
        j.is_active = False
    session.commit()
    with pytest.raises(BookingError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == NO_JOURNAL
    assert exc.value.message.startswith("Er is geen inkoopdagboek actief")


# --- double booking / duplicates --------------------------------------------------------------
def test_double_booking_refused(session, year2025, make_extraction):
    doc = make_extraction()
    book_extraction(session, doc.id)
    session.commit()
    with pytest.raises(BookingError) as exc:
        book_extraction(session, doc.id)
    assert exc.value.code == ALREADY_BOOKED
    assert exc.value.message == "Dit document is al geboekt."
    session.rollback()
    assert count(session, JournalEntry) == 1


def test_duplicate_number_same_supplier_refused(session, year2025, make_extraction, make_supplier):
    supplier = make_supplier()
    book_extraction(session, make_extraction(contact=supplier, number="F-1").id)
    session.commit()
    second = make_extraction(contact=supplier, number="  f-1 ")
    with pytest.raises(BookingError) as exc:
        book_extraction(session, second.id)
    assert exc.value.code == DUPLICATE_INVOICE
    assert exc.value.message == "Deze factuur van Bol B.V. met nummer f-1 is al geboekt."
    session.rollback()
    assert count(session, PurchaseInvoice) == 1


def test_same_number_other_supplier_allowed(session, year2025, make_extraction, make_supplier):
    book_extraction(session, make_extraction(number="F-1").id)
    other = make_supplier("Ander B.V.")
    book_extraction(session, make_extraction(contact=other, number="F-1").id)
    session.commit()
    assert count(session, PurchaseInvoice) == 2


def test_duplicate_allowed_after_storno(session, year2025, make_extraction, make_supplier):
    supplier = make_supplier()
    first = book_extraction(session, make_extraction(contact=supplier, number="F-1").id)
    reverse_entry(session, first.journal_entry_id)
    session.commit()
    again = book_extraction(session, make_extraction(contact=supplier, number="F-1").id)
    session.commit()
    assert again.id != first.id


# --- append-only ---------------------------------------------------------------------------------
def test_entry_cannot_be_changed_after_source_link(session, year2025, make_extraction):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    invoice = book_extraction(session, make_extraction().id)
    session.commit()
    for sql in [
        "UPDATE journal_entry SET source_id = 999",
        "UPDATE journal_entry SET source_type = NULL, source_id = NULL",
        "UPDATE journal_entry SET description = 'x'",
    ]:
        with pytest.raises(IntegrityError, match="onveranderlijk"):
            session.execute(text(sql))
        session.rollback()
    assert session.get(JournalEntry, invoice.journal_entry_id).source_id == invoice.id


# --- prepare_booking ---------------------------------------------------------------------------------
def test_prepare_booking_preview(session, year2025, make_extraction):
    doc = make_extraction()
    preview = prepare_booking(session, doc.id)
    assert isinstance(preview, BookingPreview)
    assert preview.can_book and preview.error is None
    assert preview.document_id == doc.id
    assert preview.supplier_name == "Bol B.V."
    assert preview.invoice_number == "F-1"
    assert preview.invoice_date == date(2025, 3, 10)
    assert preview.total_incl_cents == 12100
    assert preview.journal_code == "IK"
    assert preview.period_label == "maart 2025"
    assert [r.account_code for r in preview.rows] == ["4625", "1400", "3000"]
    assert preview.rows[0].account_name == "Kantoorbenodigdheden"
    assert preview.rows[0].vat_label == "21%"
    assert preview.summary == "Kosten € 100,00, BTW € 21,00, nog te betalen aan Bol B.V. € 121,00."
    assert preview.warnings == []
    # nothing saved
    session.rollback()
    assert count(session, JournalEntry) == 0


def test_prepare_booking_not_reviewed(session, year2025, make_extraction):
    preview = prepare_booking(session, make_extraction(reviewed=False).id)
    assert not preview.can_book
    assert preview.needs_review
    assert preview.error.code == NOT_REVIEWED


def test_prepare_booking_without_extraction(session, year2025, make_doc):
    preview = prepare_booking(session, make_doc().id)
    assert preview.needs_review and preview.rows == []


def test_prepare_booking_reports_locked_period(session, year2025, make_extraction):
    doc = make_extraction()
    lock_period(session, session.scalar(select(Period.id).where(Period.number == 3)))
    session.commit()
    preview = prepare_booking(session, doc.id)
    assert not preview.can_book and not preview.needs_review
    assert preview.error.code == "PERIOD_LOCKED"
    assert preview.rows  # still shows what would be booked


def test_prepare_booking_reports_duplicate(session, year2025, make_extraction, make_supplier):
    supplier = make_supplier()
    book_extraction(session, make_extraction(contact=supplier).id)
    session.commit()
    preview = prepare_booking(session, make_extraction(contact=supplier).id)
    assert preview.error.code == DUPLICATE_INVOICE


def test_prepare_booking_missing_field_points_to_review_field(session, year2025, make_extraction):
    doc = make_extraction(lines=[("Papier", 10000, 2100, "NL_21", None)])
    preview = prepare_booking(session, doc.id)
    assert preview.error.code == "MISSING_FIELD"
    assert preview.error.field == "line.0.account"
    assert preview.rows == []


def test_prepare_booking_already_booked(session, year2025, make_extraction):
    doc = make_extraction()
    book_extraction(session, doc.id)
    session.commit()
    preview = prepare_booking(session, doc.id)
    assert preview.error.code == ALREADY_BOOKED


def test_verlegde_btw_lands_in_the_btw_aangifte(session, year2025, make_extraction):
    from app.domain.vat.report import build_vat_report

    book_extraction(session, make_extraction(lines=[("Hosting", 10000, 0, "EU_DIENSTEN", "4625")]).id)
    session.commit()
    report = build_vat_report(session, date(2025, 1, 1), date(2025, 3, 31))
    by_rubriek = {l.rubriek: l for l in report.lines}
    assert by_rubriek["4b"].grondslag_cents == 10000
    assert by_rubriek["4b"].vat_cents == 2100
    assert report.totals["5b"] == 2100  # the same btw is deducted again
    assert report.totals["5g"] == 0
    assert report.warnings == []
