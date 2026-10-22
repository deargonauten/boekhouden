"""Web tests for the booking flow on the inbox: preview, book, errors, links.

Builder C registers the router in routes.py; the fixture below mounts it when that has not
happened yet, so these tests also run on their own. Missing glossary terms (added by C) are stubbed.
"""

import itertools

import pytest

from app.domain import glossary
from app.domain.extraction.extractors.fake import FakeExtractor
from app.domain.extraction.service import BackendStatus
from app.web import booking_routes, extraction_routes
from tests.test_extraction_web import INVOICE, PDF, add_doc, review_data, sql, use

_n = itertools.count(1)
NEW_TERMS = ("inkoopfactuur", "goedkeuren_boeken", "openstaand", "leerfunctie", "voorbelasting")


def _mounted(app) -> bool:
    return any(getattr(r, "path", "") == "/inbox/{document_id:int}/boeken" for r in app.routes)


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    monkeypatch.setattr(extraction_routes, "backend_status", lambda s: BackendStatus("claude_cli", True, ""))
    for key in NEW_TERMS:
        if key not in glossary.GLOSSARY:
            monkeypatch.setitem(glossary.GLOSSARY, key, glossary.Term(key, key.capitalize(), "Uitleg", "Uitleg."))
    if not _mounted(client.app):
        client.app.include_router(booking_routes.router)
    client.post("/instellingen/boekjaren", data={"year": 2026})
    yield
    client.app.dependency_overrides.clear()


def reviewed_doc(client, **over):
    use(client, FakeExtractor(INVOICE))
    n = next(_n)
    doc_id = add_doc(client, f"f{n}.pdf", PDF + bytes([n]))
    client.post(f"/inbox/{doc_id}/uitlezen")
    data = review_data(client, **over)
    data["actie"] = "klaar"
    r = client.post(f"/inbox/{doc_id}/nakijken", data=data, follow_redirects=False)
    assert r.status_code == 303
    return doc_id


def entries(client):
    return sql(client, "SELECT count(*) FROM journal_entry")[0][0]


# --- preview ------------------------------------------------------------------


def test_preview_shows_plain_dutch_summary_and_where_it_lands(client):
    doc_id = reviewed_doc(client)
    r = client.get(f"/inbox/{doc_id}/boeken")
    assert r.status_code == 200
    for expected in ("Zo wordt het geboekt", "Jansen Installatie", "2026-001", "01-03-2026",
                     "€ 100,00", "€ 21,00", "€ 121,00", "maart 2026", "IK", "Nog te betalen aan"):
        assert expected in r.text
    assert 'data-term="goedkeuren_boeken"' in r.text
    assert 'data-term="voorbelasting"' in r.text
    assert 'data-term="crediteuren"' in r.text
    assert "Goedkeuren en boeken" in r.text
    assert "disabled" not in r.text
    assert entries(client) == 0  # a preview writes nothing


def test_preview_before_nakijken_says_eerst_nakijken(client):
    use(client, FakeExtractor(INVOICE))
    doc_id = add_doc(client)
    client.post(f"/inbox/{doc_id}/uitlezen")
    r = client.get(f"/inbox/{doc_id}/boeken")
    assert r.status_code == 200
    assert "Eerst nakijken" in r.text
    assert f'href="/inbox/{doc_id}/nakijken"' in r.text
    assert "disabled" in r.text


def test_preview_unknown_document_is_404(client):
    assert client.get("/inbox/999/boeken").status_code == 404
    assert client.post("/inbox/999/boeken").status_code == 404


# --- booking ------------------------------------------------------------------


def test_post_books_and_redirects_to_inkoop(client):
    doc_id = reviewed_doc(client)
    r = client.post(f"/inbox/{doc_id}/boeken", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/inkoop?melding=geboekt&boeking=")
    assert sql(client, "SELECT status FROM document WHERE id = :i", i=doc_id) == [("geboekt",)]
    assert sql(client, "SELECT count(*) FROM purchase_invoice") == [(1,)]
    assert entries(client) == 1


def test_double_submit_gives_422_and_no_second_entry(client):
    doc_id = reviewed_doc(client)
    client.post(f"/inbox/{doc_id}/boeken")
    r = client.post(f"/inbox/{doc_id}/boeken")
    assert r.status_code == 422
    assert "al geboekt" in r.text
    assert "ALREADY_BOOKED" not in r.text and "Traceback" not in r.text
    assert entries(client) == 1


def test_locked_period_is_422_with_message_and_nothing_persisted(client):
    doc_id = reviewed_doc(client, invoice_date="01-03-2024")
    page = client.get(f"/inbox/{doc_id}/boeken")
    assert page.status_code == 200  # the preview shows the problem instead of failing
    assert "disabled" in page.text
    r = client.post(f"/inbox/{doc_id}/boeken")
    assert r.status_code == 422
    assert "Traceback" not in r.text
    assert sql(client, "SELECT status FROM document WHERE id = :i", i=doc_id) == [("herkend",)]
    assert sql(client, "SELECT count(*) FROM purchase_invoice") == [(0,)]
    assert entries(client) == 0


def test_duplicate_invoice_number_is_refused_with_plain_message(client):
    client.post(f"/inbox/{reviewed_doc(client)}/boeken")
    second = reviewed_doc(client)
    r = client.post(f"/inbox/{second}/boeken")
    assert r.status_code == 422
    assert "is al geboekt" in r.text and "2026-001" in r.text
    assert "Zo wordt het geboekt" in r.text  # values kept
    assert entries(client) == 1


def test_missing_item_links_to_the_review_screen(client):
    doc_id = reviewed_doc(client, line_account_code=[""])
    r = client.post(f"/inbox/{doc_id}/boeken")
    assert r.status_code == 422
    assert f'href="/inbox/{doc_id}/nakijken' in r.text


# --- review page ------------------------------------------------------------------


def test_review_page_has_book_button_only_when_ok_and_not_geboekt(client):
    doc_id = reviewed_doc(client)
    page = client.get(f"/inbox/{doc_id}/nakijken").text
    assert "Goedkeuren en boeken" in page and f'href="/inbox/{doc_id}/boeken"' in page
    client.post(f"/inbox/{doc_id}/boeken")
    assert "Goedkeuren en boeken" not in client.get(f"/inbox/{doc_id}/nakijken").text


def test_review_page_hints_what_you_chose_last_time(client):
    client.post(f"/inbox/{reviewed_doc(client)}/boeken")
    second = reviewed_doc(client, invoice_number="2026-002", line_account_code=["4900"])
    page = client.get(f"/inbox/{second}/nakijken").text
    assert "Vorige keer koos je 4200" in page
    assert 'data-term="leerfunctie"' in page


# --- links ------------------------------------------------------------------------


def test_geboekt_document_links_to_boeking_and_inkoopfactuur(client):
    doc_id = reviewed_doc(client)
    client.post(f"/inbox/{doc_id}/boeken")
    entry_id = sql(client, "SELECT journal_entry_id FROM purchase_invoice")[0][0]
    page = client.get(f"/inbox/{doc_id}").text
    assert f'href="/boeken/{entry_id}"' in page
    assert "Inkoopfactuur" in page and 'href="/inkoop"' in page


def test_entry_detail_links_back_to_the_document(client):
    doc_id = reviewed_doc(client)
    client.post(f"/inbox/{doc_id}/boeken")
    entry_id = sql(client, "SELECT journal_entry_id FROM purchase_invoice")[0][0]
    page = client.get(f"/boeken/{entry_id}").text
    assert f'href="/inbox/{doc_id}"' in page
