import threading
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.errors import LedgerError
from app.domain.ledger import lock_period, reverse_entry, trial_balance
from app.domain.relations import ContactInput, create_contact
from app.domain.sales import (
    ConceptInput,
    LineInput,
    SalesError,
    build_document,
    create_concept,
    delete_concept,
    finalize,
    get_detail,
    open_amount,
    save_concept,
)
from app.domain.sales import service as sales_service
from app.models import (
    JournalEntry,
    JournalLine,
    Period,
    SalesInvoice,
    SalesInvoiceVat,
)
from tests.sales.conftest import DAY


def counter(session, year=2026):
    return session.scalar(text("SELECT last_number FROM sales_number_counter WHERE year = :y"), {"y": year})


def test_concept_has_no_number_and_defaults(session, make_concept, customer):
    inv = make_concept(customer)
    assert inv.status == "concept" and inv.number is None
    assert inv.payment_term_days == 30
    assert inv.due_date == date(2026, 4, 9)
    assert (inv.total_excl_cents, inv.total_vat_cents, inv.total_incl_cents) == (10000, 2100, 12100)
    assert inv.lines[0].line_excl_cents == 10000
    assert counter(session) is None


def test_term_defaults_to_klant_term_and_manual_due_date(session, make_concept, make_customer):
    c = make_customer("Snel")
    c.payment_term_days = 14
    session.commit()
    inv = make_concept(c)
    assert inv.payment_term_days == 14 and inv.due_date == date(2026, 3, 24)
    inv = save_concept(
        session, inv.id,
        ConceptInput(c.id, DAY, inv_lines(inv), due_date=date(2026, 5, 1), due_date_manual=True),
    )
    assert inv.due_date == date(2026, 5, 1) and inv.due_date_manual
    inv = save_concept(session, inv.id, ConceptInput(c.id, date(2026, 3, 11), inv_lines(inv), payment_term_days=0))
    assert inv.due_date == date(2026, 3, 11) and not inv.due_date_manual


def inv_lines(inv):
    return [
        LineInput(l.description, l.quantity_milli, l.unit_price_cents, l.vat_code, l.account_id, l.unit)
        for l in inv.lines
    ]


def test_missing_account_is_suggested_from_vat_code(session, acc, make_concept, customer):
    inv = make_concept(customer, lines=[LineInput("Boek", 1000, 1000, "NL_9"), LineInput("Cadeau", 1000, 1000, "NL_0")])
    assert [l.account_id for l in inv.lines] == [acc("8401"), acc("8403")]


def test_save_concept_refuses_unsupported_vat_and_bad_numbers(session, make_concept, customer):
    inv = make_concept(customer)
    for line in [LineInput("x", 1000, 100, "VERLEGD"), LineInput("x", 0, 100, "NL_21"), LineInput("x", 1000, -1, "NL_21")]:
        with pytest.raises(SalesError):
            save_concept(session, inv.id, ConceptInput(customer.id, DAY, [line]))


def test_finalize_assigns_consecutive_numbers_and_posts_entry(session, make_final, customer, acc, storage):
    a = make_final(customer)
    b = make_final(customer)
    assert (a.number, b.number) == ("2026-0001", "2026-0002")
    assert (a.number_year, a.number_seq) == (2026, 1)
    assert a.status == "definitief" and a.finalized_at is not None
    entry = session.get(JournalEntry, a.journal_entry_id)
    assert entry.reference == "2026-0001"
    assert entry.description == "Klant BV - 2026-0001"
    assert entry.booking_date == DAY
    assert (entry.source_type, entry.source_id) == ("verkoopfactuur", a.id)
    assert entry.entry_number.startswith("VK-2026-")
    lines = session.scalars(select(JournalLine).where(JournalLine.entry_id == entry.id)).all()
    by_account = {l.account_id: l for l in lines}
    assert by_account[acc("1300")].debit_cents == 12100
    assert by_account[acc("8400")].credit_cents == 10000 and by_account[acc("8400")].vat_code == "NL_21"
    assert by_account[acc("3100")].credit_cents == 2100 and by_account[acc("3100")].vat_code is None
    vat = session.scalars(select(SalesInvoiceVat).where(SalesInvoiceVat.invoice_id == a.id)).all()
    assert [(v.vat_code, v.rate_bp, v.base_cents, v.vat_cents) for v in vat] == [("NL_21", 2100, 10000, 2100)]


def test_finalize_snapshots_seller_and_buyer_and_stores_pdf(session, make_final, customer, storage):
    inv = make_final(customer)
    assert inv.seller_name == "Jansen Webdesign" and inv.seller_kvk == "12345678"
    assert inv.seller_iban == "NL91ABNA0417164300"
    assert (inv.buyer_name, inv.buyer_city) == ("Klant BV", "Amsterdam")
    assert inv.pdf_sha256 and storage.exists(inv.pdf_sha256, "pdf")
    assert storage.open(inv.pdf_sha256, "pdf").read().startswith(b"%PDF")
    # later changes to company or klant never alter the issued invoice
    customer.name = "Anders BV"
    customer.city = "Rotterdam"
    session.commit()
    doc = build_document(session, inv.id)
    assert (doc.buyer_name, doc.buyer_city, doc.number) == ("Klant BV", "Amsterdam", "2026-0001")
    assert doc.lines[0].rate_bp == 2100 and doc.vat_groups[0].vat_cents == 2100 and not doc.is_concept


def test_build_document_for_concept_is_marked(session, make_concept, customer):
    doc = build_document(session, make_concept(customer).id)
    assert doc.is_concept and doc.number == "" and doc.seller_name == "Jansen Webdesign"
    assert doc.total_incl_cents == 12100 and doc.vat_groups[0].base_cents == 10000


def test_definitief_is_immutable_in_service_and_db(session, make_final, customer):
    inv = make_final(customer)
    with pytest.raises(SalesError) as exc:
        save_concept(session, inv.id, ConceptInput(customer.id, DAY, inv_lines(inv)))
    assert exc.value.code == "IMMUTABLE"
    assert exc.value.message == (
        "Deze factuur is definitief en kan niet meer worden gewijzigd. Maak een creditnota om iets te corrigeren."
    )
    with pytest.raises(SalesError):
        delete_concept(session, inv.id)
    with pytest.raises(SalesError):
        finalize(session, inv.id)
    # and the triggers hold even when the service is bypassed
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE sales_invoice SET note = 'x' WHERE id = :i"), {"i": inv.id})
    session.rollback()
    with pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM sales_invoice_line WHERE invoice_id = :i"), {"i": inv.id})
    session.rollback()


def test_paid_cents_can_still_change(session, make_final, customer):
    inv = make_final(customer)
    inv.paid_cents = 5000
    session.commit()
    assert open_amount(session, inv) == 7100


def test_requirements_are_checked_with_plain_messages(session, make_concept, make_customer, company):
    nameless = create_contact(session, ContactInput(name="Zonder adres", is_customer=True))
    session.commit()
    inv = make_concept(nameless)
    with pytest.raises(SalesError) as exc:
        finalize(session, inv.id)
    assert exc.value.message == "Vul het adres van Zonder adres in bij Relaties. Het moet op de factuur staan."
    assert counter(session) is None


def test_finalize_needs_company_data(session, year2026, make_customer, storage, acc):
    customer = make_customer()
    inv = create_concept(session, ConceptInput(customer.id, DAY, [LineInput("x", 1000, 100, "NL_21", acc("8400"))]))
    session.commit()
    with pytest.raises(SalesError) as exc:
        finalize(session, inv.id, storage=storage)
    assert exc.value.field == "company" and "Bedrijfsgegevens" in exc.value.message


def test_locked_period_rolls_back_number(session, make_concept, customer, storage):
    inv = make_concept(customer)
    period = session.scalar(select(Period).where(Period.start_date <= DAY, Period.end_date >= DAY))
    lock_period(session, period.id)
    session.commit()
    with pytest.raises(LedgerError):
        finalize(session, inv.id, storage=storage)
    session.rollback()
    assert counter(session) is None
    assert session.get(SalesInvoice, inv.id).number is None
    assert session.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_pdf_failure_rolls_back_everything_and_next_number_is_unchanged(
    session, make_concept, make_final, customer, storage, monkeypatch
):
    first = make_final(customer)
    inv = make_concept(customer)
    monkeypatch.setattr(sales_service.sales_pdf, "render_invoice_pdf", lambda doc: 1 / 0)
    with pytest.raises(SalesError) as exc:
        finalize(session, inv.id, storage=storage)
    assert exc.value.message == "De PDF kon niet worden gemaakt, er is niets vastgelegd. Probeer het opnieuw."
    session.rollback()
    assert counter(session) == 1  # advanced inside the failed attempt, then rolled back
    monkeypatch.undo()
    again = session.get(SalesInvoice, inv.id)
    assert again.status == "concept" and again.number is None and again.journal_entry_id is None
    finalize(session, inv.id, storage=storage)
    session.commit()
    assert (first.number, again.number) == ("2026-0001", "2026-0002")  # gapless


def test_failure_after_counter_increment_inside_same_session_keeps_counter(
    session, make_concept, make_final, customer, storage, monkeypatch
):
    make_final(customer)
    inv = make_concept(customer)
    monkeypatch.setattr(sales_service.sales_pdf, "render_invoice_pdf", lambda doc: 1 / 0)
    with pytest.raises(SalesError):
        finalize(session, inv.id, storage=storage)
    assert counter(session) == 1  # the savepoint was rolled back, even without session.rollback()


def test_year_rollover_restarts_at_one(session, make_final, customer):
    from app.domain.ledger import create_fiscal_year

    create_fiscal_year(session, 2027)
    session.commit()
    a = make_final(customer, day=date(2026, 12, 31))
    b = make_final(customer, day=date(2027, 1, 2))
    c = make_final(customer, day=date(2027, 1, 3))
    assert [a.number, b.number, c.number] == ["2026-0001", "2027-0001", "2027-0002"]


def test_date_order_guard(session, make_concept, make_final, customer, storage):
    make_final(customer, day=date(2026, 3, 20))
    inv = make_concept(customer, day=date(2026, 3, 10))
    with pytest.raises(SalesError) as exc:
        finalize(session, inv.id, storage=storage)
    assert exc.value.code == "DATE_ORDER" and "20-03-2026" in exc.value.message
    session.rollback()
    assert counter(session) == 1
    ok = make_concept(customer, day=date(2026, 3, 20))
    finalize(session, ok.id, storage=storage)  # same date is fine
    assert ok.number == "2026-0002"


def test_zero_total_refused(session, make_concept, customer, storage):
    inv = make_concept(customer, lines=[LineInput("Gratis", 1000, 0, "NL_21")])
    with pytest.raises(SalesError) as exc:
        finalize(session, inv.id, storage=storage)
    assert exc.value.message == "Het totaal is €0,00; zo'n factuur kun je niet boeken."


def test_no_sales_journal(session, make_concept, customer, storage):
    session.execute(text("UPDATE journal SET is_active = 0 WHERE type = 'verkoop'"))
    inv = make_concept(customer)
    with pytest.raises(SalesError) as exc:
        finalize(session, inv.id, storage=storage)
    assert exc.value.message == "Er is geen verkoopdagboek actief. Maak er een aan onder Instellingen."


def test_deleting_a_concept_consumes_nothing(session, make_concept, make_final, customer):
    gone = make_concept(customer)
    delete_concept(session, gone.id)
    session.commit()
    assert session.get(SalesInvoice, gone.id) is None
    assert make_final(customer).number == "2026-0001"


def test_storno_makes_invoice_gestorneerd_but_number_stays_used(session, make_final, customer):
    inv = make_final(customer)
    reverse_entry(session, inv.journal_entry_id)
    session.commit()
    detail = get_detail(session, inv.id)
    assert detail.status == "gestorneerd" and detail.open_cents == 0
    assert "creditnota" in detail.warnings[0]
    assert make_final(customer).number == "2026-0002"


def test_trial_balance_matches_documents(session, make_final, customer, acc):
    make_final(customer)
    make_final(customer, lines=[LineInput("Boek", 2000, 1000, "NL_9", None)])
    tb = {r.code: r for r in trial_balance(session)}
    assert tb["1300"].debit_cents == 12100 + 2180
    assert tb["3100"].credit_cents == 2100
    assert tb["3110"].credit_cents == 180
    assert tb["8400"].credit_cents == 10000 and tb["8401"].credit_cents == 2000


def test_mixed_lines_vat_per_group(session, make_final, customer):
    inv = make_final(
        customer,
        lines=[LineInput("a", 1000, 50, "NL_21"), LineInput("b", 1000, 50, "NL_21"), LineInput("c", 1000, 50, "NL_21")],
    )
    assert inv.total_vat_cents == 32  # 150 * 21% = 31.5 rounded once on the group
    assert inv.total_incl_cents == 182


def test_two_finalizes_in_parallel_get_distinct_numbers(engine, session, make_concept, customer, storage):
    a, b = make_concept(customer), make_concept(customer)
    session.close()
    results, errors = [], []

    def run(invoice_id):
        try:
            with Session(engine, expire_on_commit=False) as s:
                inv = finalize(s, invoice_id, storage=storage)
                s.commit()
                results.append(inv.number)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in (a.id, b.id)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert sorted(results) == ["2026-0001", "2026-0002"]


def test_stored_pdf_of_issued_invoice_has_no_concept_marker(session, make_concept, make_final, customer, storage):
    import re
    from io import BytesIO

    from pypdf import PdfReader

    def text_of(pdf: bytes) -> str:
        return re.sub(r"\s+", " ", " ".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages))

    inv = make_final(customer)
    stored = text_of(storage.open(inv.pdf_sha256, "pdf").read())
    assert "CONCEPT" not in stored and inv.number in stored
    # the preview of a concept is still marked
    concept = make_concept(customer)
    from app.domain.sales import pdf as sales_pdf

    assert "CONCEPT" in text_of(sales_pdf.render_invoice_pdf(build_document(session, concept.id)))
