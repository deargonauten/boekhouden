"""Extraction service on a migrated sqlite database."""

import json
import sys
import types
from datetime import date

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.domain.documents import get_document, mark_booked
from app.domain.errors import (
    ExtractionFailedError,
    ExtractionNotAllowedError,
    ExtractionNotFoundError,
    ExtractionRateLimitedError,
    ReviewValidationError,
)
from app.domain.extraction import service
from app.domain.extraction.review import ReviewInput, ReviewLineInput
from app.domain.extraction.types import ExtractedInvoice, ExtractedLine
from app.domain.relations import ContactInput, ExtractedContact, create_contact
from app.models import Account, Contact, InvoiceExtraction, InvoiceExtractionLine

SUPPLIER = ExtractedContact(
    name="Bol B.V.", kvk="12345678", btw_number="NL123456789B01", iban="NL91ABNA0417164300"
)


def invoice(**kw) -> ExtractedInvoice:
    base = dict(
        supplier=SUPPLIER,
        invoice_number="F-1",
        invoice_date=date.today(),
        total_excl_cents=10000,
        total_vat_cents=2100,
        total_incl_cents=12100,
        lines=(ExtractedLine("Papier", 10000, "NL_21", 2100, "4625"),),
        raw='{"raw": true}',
    )
    base.update(kw)
    return ExtractedInvoice(**base)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def form(**kw) -> ReviewInput:
    base = dict(
        supplier_name="Bol B.V.",
        supplier_btw_number="NL123456789B01",
        invoice_number="F-1",
        invoice_date=date.today().strftime("%d-%m-%Y"),
        total_excl="100,00",
        total_vat="21,00",
        total_incl="121,00",
        lines=[ReviewLineInput("Papier", "100,00", "NL_21", "21,00", "4625")],
    )
    base.update(kw)
    return ReviewInput(**base)


# --- build_request -----------------------------------------------------------------
def test_build_request(session, storage, make_doc):
    doc = make_doc("scan.pdf")
    session.execute(Account.__table__.update().where(Account.code == "4000").values(is_postable=False))
    session.commit()
    req = service.build_request(session, storage, doc.id)
    assert req.content.startswith(b"%PDF")
    assert req.content_type == "application/pdf" and req.filename == "scan.pdf"
    codes = {a.code for a in req.accounts}
    assert {"4625", "4999"} <= codes
    assert "8400" not in codes and "1210" not in codes  # expense accounts only
    assert "4000" not in codes  # not postable
    assert {"NL_21", "NL_9", "NL_0", "VERLEGD"} <= set(req.vat_codes)
    assert all(a.name for a in req.accounts)


def test_build_request_skips_inactive_accounts_and_codes(session, storage, make_doc):
    session.execute(Account.__table__.update().where(Account.code == "4625").values(is_active=False))
    session.commit()
    req = service.build_request(session, storage, make_doc().id)
    assert "4625" not in {a.code for a in req.accounts}


def test_build_request_refuses_booked_document(session, storage, make_doc, year2025, make_entry):
    doc = make_doc()
    mark_booked(session, doc.id, make_entry().id)
    session.commit()
    with pytest.raises(ExtractionNotAllowedError) as exc:
        service.build_request(session, storage, doc.id)
    assert exc.value.message == "Dit document is al geboekt en kan niet opnieuw worden uitgelezen."


# --- store_result ----------------------------------------------------------------------
def test_store_result_persists_and_marks_recognized(session, make_doc):
    doc = make_doc()
    ex = service.store_result(session, doc.id, "fake", "m1", invoice())
    session.commit()
    assert ex.status == "ok" and ex.extractor == "fake" and ex.model == "m1"
    assert ex.supplier_name == "Bol B.V." and ex.invoice_number == "F-1"
    assert (ex.total_excl_cents, ex.total_vat_cents, ex.total_incl_cents) == (10000, 2100, 12100)
    assert ex.currency == "EUR" and ex.kind == "invoice"
    assert ex.raw_json == '{"raw": true}' and ex.reviewed_at is None
    (line,) = ex.lines
    assert line.position == 0 and line.amount_excl_cents == 10000 and line.vat_code == "NL_21"
    assert line.account_id == session.scalar(select(Account.id).where(Account.code == "4625"))
    assert get_document(session, doc.id).status == "herkend"


def test_store_result_matches_existing_contact_without_creating(session, make_doc):
    existing = create_contact(
        session, ContactInput(name="Bol", is_supplier=True, btw_number="NL123456789B01")
    )
    session.commit()
    doc = make_doc()
    ex = service.store_result(session, doc.id, "fake", None, invoice())
    assert ex.contact_id == existing.id
    assert count(session, Contact) == 1


def test_store_result_does_not_create_unknown_supplier(session, make_doc):
    ex = service.store_result(session, make_doc().id, "fake", None, invoice())
    assert ex.contact_id is None
    assert count(session, Contact) == 0


def test_store_result_flags_and_clears_unusable_suggestions(session, make_doc):
    inv = invoice(
        lines=(ExtractedLine("x", 10000, "BTW21", 2100, "8400"),),
        supplier=ExtractedContact(name="Bol", kvk="123"),
    )
    ex = service.store_result(session, make_doc().id, "fake", None, inv)
    (line,) = ex.lines
    assert line.account_id is None  # revenue account is not allowed
    assert line.vat_code == "NL_21"  # inferred from the amounts
    line_fields = {f.field for f in service.line_flags(line)}
    assert line_fields == {"account", "vat_code"}
    header = {f.field: f for f in service.extraction_flags(ex)}
    assert "supplier_kvk" in header and header["supplier_kvk"].level == "low"
    assert not any(f.startswith("line.") for f in header)


def test_store_result_flags_totals_mismatch(session, make_doc):
    ex = service.store_result(
        session, make_doc().id, "fake", None, invoice(total_excl_cents=11000, total_incl_cents=13100)
    )
    flags = {f.field: f for f in service.extraction_flags(ex)}
    assert "De regels tellen op tot € 100,00" in flags["total_excl"].reason
    assert service.flagged_count(ex) >= 1


def test_store_result_relation_warnings_become_flags(session, make_doc):
    create_contact(session, ContactInput(name="Andere", is_supplier=True, kvk="12345678"))
    create_contact(session, ContactInput(name="Bol", is_supplier=True, btw_number="NL123456789B01"))
    ex = service.store_result(session, make_doc().id, "fake", None, invoice())
    flags = {f.field: f for f in service.extraction_flags(ex)}
    assert "supplier" in flags and "Controleer of dit dezelfde relatie is" in flags["supplier"].reason


def test_store_result_ambiguous_supplier_is_flagged(session, make_doc):
    create_contact(session, ContactInput(name="Bol B.V.", is_supplier=True))
    create_contact(session, ContactInput(name="bol b.v.", is_supplier=True, kvk="87654321"))
    inv = invoice(supplier=ExtractedContact(name="Bol B.V."))
    ex = service.store_result(session, make_doc().id, "fake", None, inv)
    assert ex.contact_id is None
    assert "supplier" in {f.field for f in service.extraction_flags(ex)}


def test_store_result_credit_note_amounts_stay_positive(session, make_doc):
    ex = service.store_result(session, make_doc().id, "fake", None, invoice(kind="credit_note"))
    assert ex.kind == "credit_note" and ex.total_excl_cents == 10000
    assert any(f.level == "info" for f in service.extraction_flags(ex))
    assert service.flagged_count(ex) == 0


def test_reextraction_replaces_and_clears_review(session, make_doc):
    doc = make_doc()
    first = service.store_result(session, doc.id, "fake", None, invoice())
    first_id = first.id
    service.save_review(session, doc.id, form(), finish=True)
    assert service.get_extraction(session, doc.id).reviewed_at is not None
    second = service.store_result(
        session,
        doc.id,
        "fake",
        None,
        invoice(
            invoice_number="F-2",
            lines=(ExtractedLine("a", 4000, "NL_21", 840, "4625"), ExtractedLine("b", 6000, "NL_21", 1260, "4625")),
        ),
    )
    session.commit()
    assert second.id == first_id and count(session, InvoiceExtraction) == 1
    assert second.invoice_number == "F-2" and second.reviewed_at is None
    assert [ln.position for ln in second.lines] == [0, 1]
    assert count(session, InvoiceExtractionLine) == 2
    assert get_document(session, doc.id).status == "herkend"


def test_store_result_blocked_for_booked_document(session, make_doc, year2025, make_entry):
    doc = make_doc()
    mark_booked(session, doc.id, make_entry().id)
    with pytest.raises(ExtractionNotAllowedError):
        service.store_result(session, doc.id, "fake", None, invoice())
    with pytest.raises(ExtractionNotAllowedError):
        service.store_failure(session, doc.id, "fake", ExtractionFailedError("x"))


# --- store_failure -----------------------------------------------------------------------------
def test_store_failure_keeps_document_new(session, make_doc):
    doc = make_doc()
    ex = service.store_failure(
        session, doc.id, "claude_cli", ExtractionRateLimitedError("Je Claude-limiet is bereikt.")
    )
    assert ex.status == "failed" and ex.error_code == "EXTRACTION_RATE_LIMITED"
    assert ex.error_message == "Je Claude-limiet is bereikt."
    assert get_document(session, doc.id).status == "nieuw"


def test_store_failure_hides_unexpected_error_details(session, make_doc):
    ex = service.store_failure(session, make_doc().id, "fake", RuntimeError("Traceback secret /tmp/x"))
    assert ex.error_code == "EXTRACTION_FAILED"
    assert "secret" not in ex.error_message
    assert ex.error_message.startswith("Het uitlezen is niet gelukt")


def test_retry_after_failure_replaces_the_failed_row(session, make_doc):
    doc = make_doc()
    service.store_failure(session, doc.id, "fake", ExtractionFailedError("x"))
    ex = service.store_result(session, doc.id, "fake", None, invoice())
    assert ex.status == "ok" and ex.error_code is None and ex.error_message is None
    assert count(session, InvoiceExtraction) == 1


def test_failed_reextraction_keeps_the_good_result(session, make_doc):
    doc = make_doc()
    service.store_result(session, doc.id, "fake", None, invoice())
    ex = service.store_failure(session, doc.id, "fake", ExtractionFailedError("x"))
    assert ex.status == "ok" and ex.invoice_number == "F-1"


# --- run_extraction -----------------------------------------------------------------------------
class _Extractor:
    name = "fake"
    model = "fake-1"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.requests = result, error, []

    def extract(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.result


def test_run_extraction_success(session, storage, make_doc):
    doc = make_doc()
    fake = _Extractor(invoice())
    ex = service.run_extraction(session, storage, fake, doc.id)
    assert ex.status == "ok" and ex.model == "fake-1"
    assert len(fake.requests) == 1 and fake.requests[0].content.startswith(b"%PDF")


def test_run_extraction_stores_failure_and_reraises(session, storage, make_doc):
    doc = make_doc()
    with pytest.raises(ExtractionRateLimitedError):
        service.run_extraction(session, storage, _Extractor(error=ExtractionRateLimitedError("limiet")), doc.id)
    assert service.get_extraction(session, doc.id).status == "failed"
    assert get_document(session, doc.id).status == "nieuw"


def test_run_extraction_does_not_swallow_unexpected_errors(session, storage, make_doc):
    with pytest.raises(RuntimeError):
        service.run_extraction(session, storage, _Extractor(error=RuntimeError("bug")), make_doc().id)


# --- get_extraction -------------------------------------------------------------------------------
def test_get_extraction_not_found(session, make_doc):
    doc = make_doc()
    with pytest.raises(ExtractionNotFoundError) as exc:
        service.get_extraction(session, doc.id)
    assert "Lees factuur uit" in exc.value.message
    assert service.find_extraction(session, doc.id) is None


# --- save_review ------------------------------------------------------------------------------------
@pytest.fixture
def extracted(session, make_doc):
    doc = make_doc()
    service.store_result(session, doc.id, "fake", None, invoice())
    session.commit()
    return doc


def test_save_review_updates_fields_and_lines(session, extracted):
    data = form(
        supplier_name="Bol",
        invoice_number="F-9",
        due_date="2026-12-01",
        lines=[
            ReviewLineInput("a", "40,00", "NL_21", "8,40", "4625"),
            ReviewLineInput("b", "60,00", "NL_9", "5,40", "4999"),
        ],
        total_excl="100,00",
        total_vat="13,80",
        total_incl="113,80",
    )
    result = service.save_review(session, extracted.id, data, finish=False)
    ex = result.extraction
    assert ex.supplier_name == "Bol" and ex.invoice_number == "F-9"
    assert ex.due_date == date(2026, 12, 1) and ex.total_incl_cents == 11380
    assert [(ln.amount_excl_cents, ln.vat_code) for ln in ex.lines] == [(4000, "NL_21"), (6000, "NL_9")]
    assert ex.reviewed_at is None
    assert count(session, InvoiceExtractionLine) == 2


def test_save_review_keeps_raw_json_and_document_status(session, extracted):
    service.save_review(session, extracted.id, form(invoice_number="X"), finish=True)
    ex = service.get_extraction(session, extracted.id)
    assert ex.raw_json == '{"raw": true}'
    assert get_document(session, extracted.id).status == "herkend"


def test_save_review_recomputes_flags_from_the_corrected_data(session, make_doc):
    doc = make_doc()
    service.store_result(
        session, doc.id, "fake", None, invoice(total_excl_cents=11000, total_incl_cents=13100)
    )
    assert service.flagged_count(service.get_extraction(session, doc.id)) >= 1
    result = service.save_review(session, doc.id, form(), finish=False)
    assert service.flagged_count(result.extraction) == 0


def test_save_review_validation_error_changes_nothing(session, extracted):
    with pytest.raises(ReviewValidationError) as exc:
        service.save_review(session, extracted.id, form(total_excl="abc", invoice_number="ZZZ"), finish=False)
    assert "'abc' is geen geldig bedrag" in exc.value.messages[0]
    session.rollback()
    assert service.get_extraction(session, extracted.id).invoice_number == "F-1"


def test_finish_sets_reviewed_and_creates_contact_once(session, extracted):
    assert count(session, Contact) == 0
    r1 = service.save_review(session, extracted.id, form(), finish=True)
    assert r1.extraction.reviewed_at is not None
    assert count(session, Contact) == 1
    contact = session.scalar(select(Contact))
    assert contact.name == "Bol B.V." and contact.is_supplier
    assert r1.extraction.contact_id == contact.id
    r2 = service.save_review(session, extracted.id, form(), finish=True)
    assert count(session, Contact) == 1 and r2.extraction.contact_id == contact.id


def test_plain_save_does_not_create_a_contact(session, extracted):
    service.save_review(session, extracted.id, form(), finish=False)
    assert count(session, Contact) == 0


def test_finish_returns_relation_warnings(session, extracted):
    create_contact(session, ContactInput(name="Andere", is_supplier=True, kvk="12345678"))
    create_contact(session, ContactInput(name="Bol", is_supplier=True, btw_number="NL123456789B01"))
    result = service.save_review(session, extracted.id, form(supplier_kvk="12345678"), finish=True)
    assert any("Controleer of dit dezelfde relatie is" in w for w in result.warnings)


def test_finish_requirements(session, extracted):
    with pytest.raises(ReviewValidationError) as exc:
        service.save_review(session, extracted.id, form(supplier_name="", total_excl="110,00"), finish=True)
    assert len(exc.value.messages) == 2
    assert count(session, Contact) == 0


def test_finish_with_totals_override(session, extracted):
    r = service.save_review(session, extracted.id, form(total_excl="110,00", totals_override=True), finish=True)
    assert r.extraction.reviewed_at is not None


def test_reopening_clears_reviewed_at(session, extracted):
    service.save_review(session, extracted.id, form(), finish=True)
    r = service.save_review(session, extracted.id, form(), finish=False)
    assert r.extraction.reviewed_at is None


def test_save_review_without_extraction(session, make_doc):
    with pytest.raises(ExtractionNotFoundError):
        service.save_review(session, make_doc().id, form(), finish=False)


def test_save_review_on_booked_document(session, extracted, year2025, make_entry):
    mark_booked(session, extracted.id, make_entry().id)
    with pytest.raises(ExtractionNotAllowedError):
        service.save_review(session, extracted.id, form(), finish=False)


def test_manual_entry_after_failed_extraction(session, make_doc):
    doc = make_doc()
    service.store_failure(session, doc.id, "fake", ExtractionFailedError("x"))
    r = service.save_review(session, doc.id, form(), finish=False)
    assert r.extraction.status == "ok" and r.extraction.error_code is None
    assert get_document(session, doc.id).status == "herkend"


# --- transactions ------------------------------------------------------------------------------------------
def test_service_never_commits(session, make_doc):
    doc = make_doc()
    service.store_result(session, doc.id, "fake", None, invoice())
    service.save_review(session, doc.id, form(), finish=True)
    session.rollback()
    assert count(session, InvoiceExtraction) == 0
    assert count(session, Contact) == 0
    assert get_document(session, doc.id).status == "nieuw"


def test_flags_json_is_valid_json_with_plain_dutch(session, make_doc):
    ex = service.store_result(session, make_doc().id, "fake", None, invoice(invoice_number=None))
    data = json.loads(ex.flags_json)
    assert data[0].keys() == {"field", "level", "reason"}
    assert "Niet gevonden" in data[0]["reason"]


# --- backend_status -------------------------------------------------------------------------------------------
def _stub_factory(monkeypatch, status):
    pkg = types.ModuleType("app.domain.extraction.extractors")
    pkg.__path__ = []  # act as a package
    mod = types.ModuleType("app.domain.extraction.extractors.factory")
    mod.cli_status = lambda settings: status
    monkeypatch.setitem(sys.modules, "app.domain.extraction.extractors", pkg)
    monkeypatch.setitem(sys.modules, "app.domain.extraction.extractors.factory", mod)


def _settings(**kw):
    return Settings(_env_file=None, **kw)


@pytest.mark.parametrize(
    "cli,key,backend,kind",
    [
        ("ready", None, "auto", "claude_cli"),
        ("ready", "sk-x", "auto", "claude_cli"),
        ("not_logged_in", "sk-x", "auto", "anthropic_api"),
        ("missing", "sk-x", "auto", "anthropic_api"),
        ("not_logged_in", None, "auto", "unavailable"),
        ("missing", None, "auto", "unavailable"),
        ("ready", "sk-x", "anthropic_api", "anthropic_api"),
        ("ready", None, "anthropic_api", "unavailable"),
        ("ready", "sk-x", "claude_cli", "claude_cli"),
        ("not_logged_in", "sk-x", "claude_cli", "unavailable"),
    ],
)
def test_backend_status(monkeypatch, cli, key, backend, kind):
    _stub_factory(monkeypatch, cli)
    settings = _settings(anthropic_api_key=key)
    object.__setattr__(settings, "extraction_backend", backend)
    status = service.backend_status(settings)
    assert status.kind == kind and status.available == (kind != "unavailable")
    assert status.message


def test_backend_status_messages(monkeypatch):
    _stub_factory(monkeypatch, "ready")
    assert service.backend_status(_settings()).message == "Uitlezen verloopt via je Claude-abonnement"
    _stub_factory(monkeypatch, "not_logged_in")
    s = service.backend_status(_settings())
    assert "claude auth login" in s.message
    _stub_factory(monkeypatch, "not_logged_in")
    assert service.backend_status(_settings(anthropic_api_key="k")).message == "Uitlezen verloopt via je API-sleutel"
    _stub_factory(monkeypatch, "missing")
    assert "niet gevonden" in service.backend_status(_settings()).message


def test_source_text_is_stored_and_survives_review_save(session, make_doc):
    doc = make_doc()
    inv = invoice(lines=(ExtractedLine("Papier", 10000, "NL_21", 2100, "4625", source_text="Papier A4 100,00"),))
    ex = service.store_result(session, doc.id, "fake", "m1", inv)
    session.commit()
    assert ex.lines[0].source_text == "Papier A4 100,00"

    data = form(lines=[ReviewLineInput("Papier", "100,00", "NL_21", "21,00", "4625", "Papier A4 100,00")])
    service.save_review(session, doc.id, data, finish=False)
    session.commit()
    session.refresh(ex)
    assert ex.lines[0].source_text == "Papier A4 100,00"
