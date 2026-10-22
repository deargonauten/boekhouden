"""PDF renderer: art. 35a fields, credit note wording, determinism, multi-page. No database."""

import re
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from app.domain.sales.amounts import compute_totals
from app.domain.sales.pdf import render_invoice_pdf, render_reminder_pdf
from app.domain.sales.types import DocumentLine, InvoiceDocument, LineInput, ReminderDocument, VatGroup

RATES = {"NL_21": 2100, "NL_9": 900, "NL_0": 0}


def make_doc(n_lines: int = 2, **over) -> InvoiceDocument:
    inputs = [LineInput(f"Werkzaamheden {i + 1}", 1500, 12345 + i, "NL_21" if i % 3 else "NL_9") for i in range(n_lines)]
    totals = compute_totals(inputs, RATES)
    lines = tuple(
        DocumentLine(l.description, l.quantity_milli, l.unit, l.unit_price_cents, l.vat_code, RATES[l.vat_code], amt)
        for l, amt in zip(inputs, totals.line_excl_cents)
    )
    values = dict(
        kind="invoice", number="2026-0007", invoice_date=date(2026, 3, 10), due_date=date(2026, 4, 9),
        payment_term_days=30, seller_name="Jansen Webdesign", seller_address_line="Dorpsstraat 1",
        seller_postal_code="1234 AB", seller_city="Utrecht", seller_country="NL", seller_kvk="12345678",
        seller_btw_id="NL123456789B01", seller_iban="NL91ABNA0417164300", seller_email="info@jansen.nl",
        buyer_name="Klant BV", buyer_address_line="Hoofdweg 2", buyer_postal_code="1000 AA",
        buyer_city="Amsterdam", buyer_country="NL", buyer_btw_number="NL987654321B01", buyer_kvk="87654321",
        lines=lines, vat_groups=totals.groups, total_excl_cents=totals.total_excl_cents,
        total_vat_cents=totals.total_vat_cents, total_incl_cents=totals.total_incl_cents,
    )
    values.update(over)
    return InvoiceDocument(**values)


def one_line_doc(**over) -> InvoiceDocument:
    values = dict(
        lines=(DocumentLine("Website", 1000, "stuk", 10000, "NL_21", 2100, 10000),),
        vat_groups=(VatGroup("NL_21", 2100, 10000, 2100),), total_excl_cents=10000,
        total_vat_cents=2100, total_incl_cents=12100,
    )
    values.update(over)
    return make_doc(1, **values)


def text_of(pdf: bytes) -> str:
    reader = PdfReader(BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() for page in reader.pages))


def pages_of(pdf: bytes) -> int:
    return len(PdfReader(BytesIO(pdf)).pages)


def test_starts_with_pdf_header():
    assert render_invoice_pdf(make_doc()).startswith(b"%PDF")


def test_invoice_has_all_required_fields():
    doc = make_doc()
    text = text_of(render_invoice_pdf(doc))
    for needle in (
        "Factuur", "2026-0007", "10-03-2026", "09-04-2026", "30 dagen",
        "Jansen Webdesign", "Dorpsstraat 1", "1234 AB Utrecht", "12345678", "NL123456789B01",
        "NL91ABNA0417164300", "info@jansen.nl",
        "Klant BV", "Hoofdweg 2", "1000 AA Amsterdam", "NL987654321B01", "87654321",
        "Werkzaamheden 1", "1,5 stuk", "Totaal excl. BTW", "Totaal incl. BTW",
    ):
        assert needle in text, needle
    for group in doc.vat_groups:
        assert f"BTW {group.rate_bp // 100}% over €" in text
    assert "€" in text


def test_totals_and_payment_instruction():
    text = text_of(render_invoice_pdf(one_line_doc()))
    assert "BTW 21% over € 100,00 € 21,00" in text
    assert "Totaal incl. BTW € 121,00" in text
    assert "Wij ontvangen het bedrag graag vóór 09-04-2026 op NL91ABNA0417164300 onder vermelding van 2026-0007" in text


def test_direct_betalen_label():
    text = text_of(render_invoice_pdf(make_doc(payment_term_days=0, due_date=date(2026, 3, 10))))
    assert "direct betalen" in text


def test_service_date_and_reference_only_when_set():
    base = text_of(render_invoice_pdf(make_doc()))
    assert "Leverdatum" not in base and "Uw referentie" not in base
    same = text_of(render_invoice_pdf(make_doc(service_date=date(2026, 3, 10))))
    assert "Leverdatum" not in same
    full = text_of(render_invoice_pdf(make_doc(service_date=date(2026, 3, 1), reference="PO-77", note="Bedankt!")))
    assert "Leverdatum 01-03-2026" in full and "Uw referentie PO-77" in full and "Bedankt!" in full


def test_optional_buyer_numbers_omitted_when_unknown():
    text = text_of(render_invoice_pdf(make_doc(buyer_btw_number=None, buyer_kvk=None)))
    assert "BTW-nummer" not in text and "KvK-nummer" not in text


def test_credit_note_wording():
    doc = make_doc(kind="credit_note", number="2026-0008", credited_number="2026-0007",
                   credited_date=date(2026, 3, 10), due_date=date(2026, 3, 10), payment_term_days=0)
    text = text_of(render_invoice_pdf(doc))
    assert "Creditnota" in text
    assert "Creditnota bij factuur 2026-0007 van 10-03-2026" in text
    assert "u ontvangt dit bedrag terug / dit bedrag wordt verrekend" in text
    assert "Wij ontvangen het bedrag" not in text
    assert "Vervaldatum" not in text
    assert "-€" not in text  # amounts are printed positive


def test_concept_is_marked_and_has_no_number():
    text = text_of(render_invoice_pdf(make_doc(number="", is_concept=True)))
    assert "CONCEPT" in text
    assert "2026-0007" not in text


def test_definitief_is_not_marked_concept():
    assert "CONCEPT" not in text_of(render_invoice_pdf(make_doc()))


def test_rerender_is_byte_identical():
    doc = make_doc(5)
    assert render_invoice_pdf(doc) == render_invoice_pdf(doc)


def test_different_data_gives_different_bytes():
    assert render_invoice_pdf(make_doc()) != render_invoice_pdf(make_doc(number="2026-0009"))


def test_sixty_lines_span_pages_and_keep_totals_together():
    pdf = render_invoice_pdf(make_doc(60))
    assert pages_of(pdf) >= 2
    last = re.sub(r"\s+", " ", PdfReader(BytesIO(pdf)).pages[-1].extract_text())
    assert "Totaal incl. BTW" in last and "Wij ontvangen het bedrag" in last
    assert "Werkzaamheden 60" in text_of(pdf)
    assert "Pagina 1 van" in text_of(pdf)


def test_header_row_repeats_on_each_page():
    for page in PdfReader(BytesIO(render_invoice_pdf(make_doc(60)))).pages:
        assert "Omschrijving" in page.extract_text()


def test_footer_has_company_data_on_every_page():
    for page in PdfReader(BytesIO(render_invoice_pdf(make_doc(60)))).pages:
        text = re.sub(r"\s+", " ", page.extract_text())
        assert "KvK 12345678" in text and "BTW-id NL123456789B01" in text


def test_long_description_wraps_and_special_characters_are_kept_literal():
    line = DocumentLine("Onderhoud & <b>support</b> " + "woord " * 80, 1000, "stuk", 100, "NL_21", 2100, 100)
    doc = make_doc(1, lines=(line,), vat_groups=(VatGroup("NL_21", 2100, 100, 21),), total_excl_cents=100,
                   total_vat_cents=21, total_incl_cents=121)
    assert "Onderhoud & <b>support</b>" in text_of(render_invoice_pdf(doc))


def test_reminder_pdf_contains_the_facts():
    doc = ReminderDocument(
        level=2, title="Tweede herinnering", reminder_date=date(2026, 5, 1), new_due_date=date(2026, 5, 15),
        open_cents=12100, body_text="Beste Klant BV,\n\nWe hebben nog geen betaling gezien.\n\nMet vriendelijke groet,",
        invoice_number="2026-0007", invoice_date=date(2026, 3, 10), due_date=date(2026, 4, 9),
        seller_name="Jansen Webdesign", seller_address_line="Dorpsstraat 1", seller_postal_code="1234 AB",
        seller_city="Utrecht", seller_country="NL", seller_kvk="12345678", seller_btw_id="NL123456789B01",
        seller_iban="NL91ABNA0417164300", buyer_name="Klant BV", buyer_address_line="Hoofdweg 2",
        buyer_postal_code="1000 AA", buyer_city="Amsterdam", buyer_country="NL",
    )
    pdf = render_reminder_pdf(doc)
    assert pdf.startswith(b"%PDF")
    text = text_of(pdf)
    for needle in ("Tweede herinnering", "2026-0007", "€ 121,00", "15-05-2026", "09-04-2026", "10-03-2026",
                   "Klant BV", "Hoofdweg 2", "Jansen Webdesign", "We hebben nog geen betaling gezien."):
        assert needle in text, needle
    assert render_reminder_pdf(doc) == pdf
