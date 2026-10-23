"""Learned supplier defaults (leerfunctie) and the extraction hook."""

from datetime import date, datetime

from sqlalchemy import select

from app.domain.extraction import service as extraction_service
from app.domain.extraction.review import ReviewInput, ReviewLineInput
from app.domain.extraction.types import ExtractedInvoice, ExtractedLine
from app.domain.ledger import set_account_active
from app.domain.purchase import learned
from app.domain.purchase.booking import BookingLineInput
from app.domain.relations import ExtractedContact
from app.models import Account, InvoiceExtraction, SupplierDefault, VatCode


def bl(account_id, vat_code="NL_21"):
    return BookingLineInput(
        description="x", account_id=account_id, vat_code=vat_code, amount_excl_cents=100, vat_amount_cents=21
    )


def rows(session, contact_id):
    return {
        r.account_id: (r.vat_code, r.use_count)
        for r in session.scalars(select(SupplierDefault).where(SupplierDefault.contact_id == contact_id))
    }


# --- record_booking ----------------------------------------------------------------------
def test_record_creates_and_updates_counts(session, make_supplier, acc):
    s = make_supplier()
    learned.record_booking(session, s.id, [bl(acc("4625"))])
    learned.record_booking(session, s.id, [bl(acc("4625"), "NL_9"), bl(acc("4635"))])
    session.commit()
    assert rows(session, s.id) == {acc("4625"): ("NL_9", 2), acc("4635"): ("NL_21", 1)}


def test_suggestion_none_without_history(session, make_supplier):
    assert learned.suggest_for_contact(session, make_supplier().id) is None
    assert learned.suggest_for_contact(session, None) is None


def test_suggestion_highest_count_wins(session, make_supplier, acc):
    s = make_supplier()
    learned.record_booking(session, s.id, [bl(acc("4625"))])
    learned.record_booking(session, s.id, [bl(acc("4625"))])
    learned.record_booking(session, s.id, [bl(acc("4635"), "NL_9")])
    sug = learned.suggest_for_contact(session, s.id)
    assert sug.account_id == acc("4625")
    assert sug.account_code == "4625"
    assert sug.account_name == "Kantoorbenodigdheden"
    assert sug.vat_code == "NL_21"
    assert sug.hint == "Vorige keer koos je 4625 Kantoorbenodigdheden voor deze leverancier."


def test_suggestion_tie_goes_to_most_recent(session, make_supplier, acc, monkeypatch):
    s = make_supplier()
    monkeypatch.setattr(learned, "_now", lambda: datetime(2025, 1, 1))
    learned.record_booking(session, s.id, [bl(acc("4625"))])
    monkeypatch.setattr(learned, "_now", lambda: datetime(2025, 2, 1))
    learned.record_booking(session, s.id, [bl(acc("4635"), "NL_9")])
    sug = learned.suggest_for_contact(session, s.id)
    assert (sug.account_id, sug.vat_code) == (acc("4635"), "NL_9")


def test_inactive_or_non_postable_learned_account_is_ignored(session, make_supplier, acc):
    s = make_supplier()
    learned.record_booking(session, s.id, [bl(acc("4625")), bl(acc("4625")), bl(acc("4635"))])
    set_account_active(session, acc("4625"), False)
    assert learned.suggest_for_contact(session, s.id).account_id == acc("4635")
    session.execute(Account.__table__.update().where(Account.code == "4635").values(is_postable=False))
    assert learned.suggest_for_contact(session, s.id) is None


def test_inactive_learned_vat_code_falls_back_to_account_default(session, make_supplier, acc):
    s = make_supplier()
    learned.record_booking(session, s.id, [bl(acc("4625"), "NL_9")])
    session.execute(VatCode.__table__.update().where(VatCode.code == "NL_9").values(is_active=False))
    assert learned.suggest_for_contact(session, s.id).vat_code == "NL_21"  # 4625's standaard btw-tarief


# --- extraction hook -----------------------------------------------------------------------
SUPPLIER = ExtractedContact(name="Bol B.V.", btw_number="NL123456789B01")


def invoice(*lines) -> ExtractedInvoice:
    return ExtractedInvoice(
        supplier=SUPPLIER,
        invoice_number="F-1",
        invoice_date=date.today(),
        total_excl_cents=sum(l.amount_excl_cents for l in lines),
        total_vat_cents=sum(l.vat_amount_cents or 0 for l in lines),
        total_incl_cents=sum(l.amount_excl_cents + (l.vat_amount_cents or 0) for l in lines),
        lines=tuple(lines),
    )


def supplier_with_history(session, acc, account="4635", vat="NL_9"):
    from app.domain.relations import ContactInput, create_contact

    contact = create_contact(
        session, ContactInput(name="Bol B.V.", btw_number="NL123456789B01", is_supplier=True)
    )
    session.flush()
    learned.record_booking(session, contact.id, [bl(acc(account), vat)])
    session.commit()
    return contact


def stored_lines(session, doc_id):
    ex = session.scalar(select(InvoiceExtraction).where(InvoiceExtraction.document_id == doc_id))
    session.refresh(ex)
    return [(ln.account_id, ln.vat_code) for ln in ex.lines]


def test_store_result_fills_empty_lines_from_history(session, make_doc, acc):
    contact = supplier_with_history(session, acc)
    doc = make_doc()
    inv = invoice(
        ExtractedLine("Leeg", 1000, None, None, None),  # nothing known
        ExtractedLine("Ai-keuze", 1000, "NL_21", 210, "4625"),  # AI filled a valid account
        ExtractedLine("Afgeleid", 1000, None, 90, None),  # vat inferred from amounts (NL_9)
        ExtractedLine("Eigen code", 1000, "NL_21", 210, None),  # explicit vat code kept
    )
    ex = extraction_service.store_result(session, doc.id, "test", None, inv)
    session.commit()
    assert ex.contact_id == contact.id
    assert stored_lines(session, doc.id) == [
        (acc("4635"), "NL_9"),
        (acc("4625"), "NL_21"),
        (acc("4635"), "NL_9"),
        (acc("4635"), "NL_21"),
    ]


def test_store_result_inferred_vat_replaced_by_learned(session, make_doc, acc):
    supplier_with_history(session, acc, account="4635", vat="NL_21")
    doc = make_doc()
    extraction_service.store_result(
        session, doc.id, "test", None, invoice(ExtractedLine("Afgeleid", 1000, None, 90, None))
    )
    assert stored_lines(session, doc.id) == [(acc("4635"), "NL_21")]


def test_store_result_without_history_keeps_ai_values(session, make_doc, acc):
    doc = make_doc()
    extraction_service.store_result(
        session,
        doc.id,
        "test",
        None,
        invoice(ExtractedLine("Leeg", 1000, None, None, None), ExtractedLine("Ai", 1000, "NL_21", 210, "4625")),
    )
    assert stored_lines(session, doc.id) == [(None, None), (acc("4625"), "NL_21")]


def test_save_review_fills_lines_left_empty(session, make_doc, acc):
    supplier_with_history(session, acc)
    doc = make_doc()
    extraction_service.store_result(
        session, doc.id, "test", None, invoice(ExtractedLine("Ai", 1000, "NL_21", 210, "4625"))
    )
    session.commit()
    form = ReviewInput(
        supplier_name="Bol B.V.",
        supplier_btw_number="NL123456789B01",
        invoice_number="F-1",
        invoice_date=date.today().strftime("%d-%m-%Y"),
        total_excl="20,00",
        total_vat="2,10",
        total_incl="22,10",
        lines=[
            ReviewLineInput("Eigen keuze", "10,00", "NL_21", "2,10", "4625"),
            ReviewLineInput("Leeg gelaten", "10,00", "", "0,00", ""),
        ],
    )
    extraction_service.save_review(session, doc.id, form, finish=False)
    session.commit()
    assert stored_lines(session, doc.id) == [(acc("4625"), "NL_21"), (acc("4635"), "NL_9")]


def test_apply_to_lines_returns_suggestion(session, make_doc, acc):
    contact = supplier_with_history(session, acc)
    doc = make_doc()
    ex = extraction_service.store_result(
        session, doc.id, "test", None, invoice(ExtractedLine("Ai", 1000, "NL_21", 210, "4625"))
    )
    sug = learned.apply_to_lines(session, ex)
    assert sug.contact_id == contact.id and sug.account_code == "4635"
    assert stored_lines(session, doc.id) == [(acc("4625"), "NL_21")]  # AI value kept
