"""Buitenlandse facturen end-to-end: nakijken met valuta en koers, boekscherm, boeking, btw-aangifte."""

import itertools

import pytest

from app.domain.extraction.extractors.fake import FakeExtractor
from app.domain.extraction.service import BackendStatus
from app.domain.extraction.types import ExtractedInvoice, ExtractedLine
from app.domain.relations import ExtractedContact
from app.web import booking_routes, extraction_routes
from tests.test_extraction_web import PDF, add_doc, review_data, sql, use

_n = itertools.count(1)
HETZNER = ExtractedInvoice(
    supplier=ExtractedContact(name="Hetzner Online GmbH", country="DE", btw_number="DE812871812"),
    invoice_number="R-1",
    invoice_date=__import__("datetime").date(2026, 3, 1),
    currency="USD",
    total_excl_cents=10000,
    total_vat_cents=0,
    total_incl_cents=10000,
    lines=(ExtractedLine(description="Hosting", amount_excl_cents=10000, vat_amount_cents=0),),
)


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    monkeypatch.setattr(extraction_routes, "backend_status", lambda s: BackendStatus("claude_cli", True, ""))
    if not any(getattr(r, "path", "") == "/inbox/{document_id:int}/boeken" for r in client.app.routes):
        client.app.include_router(booking_routes.router)
    client.post("/instellingen/boekjaren", data={"year": 2026})
    yield
    client.app.dependency_overrides.clear()


def foreign_doc(client):
    use(client, FakeExtractor(HETZNER))
    n = next(_n)
    doc_id = add_doc(client, f"h{n}.pdf", PDF + bytes([n]))
    client.post(f"/inbox/{doc_id}/uitlezen")
    return doc_id


def form(**over):
    data = review_data(
        None, supplier_name="Hetzner Online GmbH", supplier_country="DE", invoice_number="R-1", currency="USD",
        total_excl="100,00", total_vat="0,00", total_incl="100,00", line_vat_code=["EU_DIENSTEN"],
        line_vat_amount=["0,00"], exchange_rate="1,25", shifted_vat_rate="21",
    )
    data.update(over)
    return data


def test_reading_suggests_verlegd_code_for_a_supplier_in_the_eu(client):
    doc_id = foreign_doc(client)
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    assert 'value="EU_DIENSTEN"' in html and "selected" in html.split('value="EU_DIENSTEN"')[1][:200]
    assert 'id="exchange_rate"' in html and "Wisselkoers" in html
    assert 'data-term="wisselkoers"' in html


def test_foreign_invoice_without_exchange_rate_cannot_be_finished(client):
    doc_id = foreign_doc(client)
    r = client.post(f"/inbox/{doc_id}/nakijken", data=form(exchange_rate="", actie="klaar"))
    assert r.status_code == 422
    assert "wisselkoers" in r.text.lower() and "USD" in r.text


def test_review_book_and_btw_aangifte(client):
    doc_id = foreign_doc(client)
    r = client.post(f"/inbox/{doc_id}/nakijken", data=form(actie="klaar"), follow_redirects=False)
    assert r.status_code == 303
    page = client.get(f"/inbox/{doc_id}/boeken")
    assert page.status_code == 200
    for expected in ("€ 80,00", "USD 100,00", "1,25", "verlegd", "€ 16,80"):
        assert expected in page.text
    assert client.post(f"/inbox/{doc_id}/boeken", follow_redirects=False).status_code in (200, 303)

    assert sql(client, "SELECT currency, exchange_rate_micro, original_total_incl_cents, total_incl_cents "
                       "FROM purchase_invoice") == [("USD", 1_250_000, 10000, 8000)]
    rows = dict(sql(client, "SELECT a.code, sum(l.debit_cents - l.credit_cents) FROM journal_line l "
                            "JOIN account a ON a.id = l.account_id GROUP BY a.code"))
    assert rows["3000"] == -8000 and rows["1410"] == 1680 and rows["3130"] == -1680

    aangifte = client.get("/btw?jaar=2026&periode=Q1")
    assert aangifte.status_code == 200
