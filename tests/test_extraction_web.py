"""Web tests for reading out (uitlezen) and reviewing (nakijken) inbox documents.

All tests inject a FakeExtractor; nothing touches the network or a real `claude`.
"""

import json
from datetime import date

import pytest
from sqlalchemy import text

from app.domain.errors import (
    ExtractionFailedError,
    ExtractionRateLimitedError,
    ExtractorUnavailableError,
)
from app.domain.extraction.service import BackendStatus
from app.domain.extraction.extractors.fake import FakeExtractor
from app.domain.extraction.types import ExtractedInvoice, ExtractedLine
from app.domain.relations import ExtractedContact
from app.web import extraction_routes
from app.web.extraction_routes import get_extractor_dep
from tests.web_helpers import assert_plain_language

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

INVOICE = ExtractedInvoice(
    supplier=ExtractedContact(name="Jansen Installatie", kvk="12345678"),
    invoice_number="2026-001",
    invoice_date=date(2026, 3, 1),
    total_excl_cents=10000,
    total_vat_cents=2100,
    total_incl_cents=12100,
    lines=(
        ExtractedLine(
            description="Kantoorspullen",
            amount_excl_cents=10000,
            vat_code="NL_21",
            vat_amount_cents=2100,
        ),
    ),
)


@pytest.fixture(autouse=True)
def cli_ready(monkeypatch):
    monkeypatch.setattr(extraction_routes, "backend_status", lambda settings: BackendStatus("claude_cli", True, ""))


def use(client, extractor):
    client.app.dependency_overrides[get_extractor_dep] = lambda: extractor
    return extractor


@pytest.fixture(autouse=True)
def _clean_overrides(client):
    yield
    client.app.dependency_overrides.clear()


def add_doc(client, name="factuur.pdf", data=PDF):
    client.post("/inbox/upload", files=[("files", (name, data, "application/pdf"))])
    with client.app.state.engine.connect() as conn:
        return conn.execute(text("SELECT max(id) FROM document")).scalar()


def doc_status(client, doc_id):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text("SELECT status FROM document WHERE id = :i"), {"i": doc_id}).scalar()


def sql(client, query, **params):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(query), params).all()


def account_id(client, code="4200"):
    return sql(client, "SELECT id FROM account WHERE code = :c", c=code)[0][0]


def book(client, doc_id):
    """Mark a document geboekt, linked to a real journal entry."""
    client.post("/instellingen/boekjaren", data={"year": date.today().year})
    journal = sql(client, "SELECT id FROM journal WHERE code = 'MEM'")[0][0]
    accounts = [r[0] for r in sql(client, "SELECT id FROM account WHERE code IN ('4200','1210') ORDER BY code")]
    r = client.post(
        "/boeken/nieuw",
        data={
            "journal_id": str(journal),
            "booking_date": date.today().isoformat(),
            "description": "x",
            "reference": "",
            "line_account": [str(accounts[1]), str(accounts[0])],
            "line_debit": ["10,00", ""],
            "line_credit": ["", "10,00"],
            "line_vat": ["", ""],
            "line_description": ["", ""],
        },
        follow_redirects=False,
    )
    entry_id = int(r.headers["location"].rsplit("/", 1)[1])
    with client.app.state.engine.begin() as conn:
        conn.execute(
            text("UPDATE document SET status = 'geboekt', journal_entry_id = :e WHERE id = :i"),
            {"e": entry_id, "i": doc_id},
        )


def read_out(client, extractor=None):
    use(client, extractor or FakeExtractor(INVOICE))
    doc_id = add_doc(client)
    r = client.post(f"/inbox/{doc_id}/uitlezen", follow_redirects=False)
    assert r.status_code == 303
    return doc_id


def review_data(client, **over):
    data = {
        "supplier_name": "Jansen Installatie",
        "invoice_number": "2026-001",
        "invoice_date": "01-03-2026",
        "currency": "EUR",
        "total_excl": "100,00",
        "total_vat": "21,00",
        "total_incl": "121,00",
        "line_description": ["Kantoorspullen"],
        "line_amount_excl": ["100,00"],
        "line_vat_code": ["NL_21"],
        "line_vat_amount": ["21,00"],
        "line_account_code": ["4200"],
        "actie": "opslaan",
    }
    data.update(over)
    return data


# --- uitlezen ----------------------------------------------------------------


def test_uitlezen_success_redirects_and_marks_herkend(client):
    fake = use(client, FakeExtractor(INVOICE))
    doc_id = add_doc(client)
    r = client.post(f"/inbox/{doc_id}/uitlezen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/inbox/{doc_id}/nakijken"
    assert doc_status(client, doc_id) == "herkend"
    assert len(fake.requests) == 1 and fake.requests[0].content == PDF


def test_uitlezen_unavailable_shows_plain_dutch_and_keeps_nieuw(client):
    err = ExtractorUnavailableError(
        "Het uitlezen kan nog niet: je bent niet ingelogd bij Claude. "
        "Open Terminal en typ: claude auth login."
    )
    use(client, FakeExtractor(error=err))
    doc_id = add_doc(client)
    r = client.post(f"/inbox/{doc_id}/uitlezen")
    assert r.status_code == 200
    assert "claude auth login" in r.text
    assert "EXTRACTOR_UNAVAILABLE" not in r.text and "Traceback" not in r.text
    assert doc_status(client, doc_id) == "nieuw"
    assert sql(client, "SELECT status FROM invoice_extraction") == [("failed",)]


def test_uitlezen_failure_then_retry_replaces_the_failed_row(client):
    use(client, FakeExtractor(error=ExtractionFailedError("Het uitlezen is niet gelukt.")))
    doc_id = add_doc(client)
    assert client.post(f"/inbox/{doc_id}/uitlezen").status_code == 200
    page = client.get(f"/inbox/{doc_id}/nakijken")
    assert "Het uitlezen is niet gelukt" in page.text and "Opnieuw proberen" in page.text
    use(client, FakeExtractor(INVOICE))
    assert client.post(f"/inbox/{doc_id}/uitlezen", follow_redirects=False).status_code == 303
    assert sql(client, "SELECT status FROM invoice_extraction") == [("ok",)]


def test_uitlezen_booked_document_is_not_allowed(client):
    use(client, FakeExtractor(INVOICE))
    doc_id = add_doc(client)
    book(client, doc_id)
    r = client.post(f"/inbox/{doc_id}/uitlezen")
    assert r.status_code == 422
    assert "al geboekt" in r.text


def test_uitlezen_unknown_document_is_404(client):
    use(client, FakeExtractor(INVOICE))
    assert client.post("/inbox/999/uitlezen").status_code == 404
    assert client.get("/inbox/999/nakijken").status_code == 404
    assert client.get("/inbox/999/nakijken/regel").status_code == 404
    assert client.post("/inbox/999/nakijken", data={}).status_code == 404


# --- uitlezen-alles ------------------------------------------------------------


def test_batch_reads_new_documents_with_per_document_result(client):
    fake = use(client, FakeExtractor(INVOICE))
    for i in range(2):
        add_doc(client, f"f{i}.pdf", PDF + bytes([i]))
    r = client.post("/inbox/uitlezen-alles")
    assert r.status_code == 200
    assert "Gelukt" in r.text and r.text.count("Gelukt - ") == 2
    assert len(fake.requests) == 2
    assert sql(client, "SELECT status FROM document") == [("herkend",), ("herkend",)]


def test_batch_is_capped_at_ten_and_says_how_many_are_left(client):
    fake = use(client, FakeExtractor(INVOICE))
    for i in range(12):
        add_doc(client, f"f{i}.pdf", PDF + bytes([i]))
    r = client.post("/inbox/uitlezen-alles")
    assert len(fake.requests) == 10
    assert "zijn nog 2 documenten niet uitgelezen" in r.text


def test_batch_stops_early_when_the_limit_is_reached(client):
    err = ExtractionRateLimitedError("Je Claude-limiet is bereikt. Probeer het over een uur nog eens.")
    fake = use(client, FakeExtractor(error=err))
    for i in range(3):
        add_doc(client, f"f{i}.pdf", PDF + bytes([i]))
    r = client.post("/inbox/uitlezen-alles")
    assert len(fake.requests) == 1
    assert "Mislukt: Je Claude-limiet is bereikt" in r.text
    assert "zijn nog 2 documenten niet uitgelezen" in r.text


def test_batch_survives_one_failing_document(client):
    class Flaky(FakeExtractor):
        def extract(self, request):
            self.error = ExtractionFailedError("Het uitlezen is niet gelukt.") if not self.requests else None
            return super().extract(request)

    use(client, Flaky(INVOICE))
    for i in range(2):
        add_doc(client, f"f{i}.pdf", PDF + bytes([i]))
    r = client.post("/inbox/uitlezen-alles")
    assert "Mislukt: Het uitlezen is niet gelukt." in r.text and "Gelukt - " in r.text


# --- inbox / detail ------------------------------------------------------------


def test_inbox_shows_actions_banner_and_privacy_note(client):
    doc_id = add_doc(client)
    html = client.get("/inbox").text
    assert "Uitlezen verloopt via je Claude-abonnement" not in html  # text has the info icon in between
    assert "verloopt via je Claude-abonnement" in html
    assert "wordt naar Claude (Anthropic) gestuurd" in html
    assert "Lees alle nieuwe documenten uit (1)" in html
    assert f'action="/inbox/{doc_id}/uitlezen"' in html
    assert "Bezig met uitlezen, dit duurt 10 tot 60 seconden" in html


def test_banner_variants(client, monkeypatch):
    add_doc(client)
    monkeypatch.setattr(extraction_routes, "backend_status", lambda s: BackendStatus("anthropic_api", True, ""))
    assert "verloopt via je API-sleutel" in client.get("/inbox").text
    monkeypatch.setattr(extraction_routes, "backend_status", lambda s: BackendStatus("unavailable", False, ""))
    html = client.get("/inbox").text
    assert "Niet ingelogd bij Claude: open Terminal en typ" in html and "claude auth login" in html


def test_herkend_document_links_to_nakijken(client):
    doc_id = read_out(client)
    assert f'href="/inbox/{doc_id}/nakijken"' in client.get("/inbox").text
    assert f'href="/inbox/{doc_id}/nakijken"' in client.get(f"/inbox/{doc_id}").text


# --- nakijken --------------------------------------------------------------------


def test_review_without_extraction_offers_the_button(client):
    doc_id = add_doc(client)
    r = client.get(f"/inbox/{doc_id}/nakijken")
    assert r.status_code == 200
    assert "Lees factuur uit" in r.text and f'action="/inbox/{doc_id}/uitlezen"' in r.text


def test_review_shows_viewer_data_and_new_supplier(client):
    doc_id = read_out(client)
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    assert f'src="/inbox/{doc_id}/bestand"' in html
    assert 'value="Jansen Installatie"' in html and 'value="2026-001"' in html
    assert 'value="01-03-2026"' in html and 'value="100,00"' in html
    assert "Nieuwe leverancier: wordt aangemaakt als je op Klaar met nakijken klikt" in html
    assert "om te controleren" in html  # real validation flags the missing grootboek suggestion
    assert "Kies een rekening. Twijfel je? Kies 4999 Nog te verdelen." in html


def test_review_shows_flags_with_labels_and_count(client):
    doc_id = read_out(client)
    flags = [{"field": "invoice_date", "level": "medium", "reason": "Controleer de datum"}]
    line_flags = [{"field": "vat_amount_cents", "level": "low", "reason": "BTW klopt niet met het tarief"}]
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE invoice_extraction SET flags_json = :f"), {"f": json.dumps(flags)})
        conn.execute(text("UPDATE invoice_extraction_line SET flags_json = :f"), {"f": json.dumps(line_flags)})
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    assert "2 velden om te controleren" in html
    assert "Controleer de datum" in html and ">Controleer<" in html
    assert "BTW klopt niet met het tarief" in html and ">Onzeker<" in html


def test_review_preselects_known_supplier(client):
    c = client.post(
        "/relaties/nieuw",
        data={"name": "Jansen Installatie", "is_supplier": "1", "kvk": "12345678"},
        follow_redirects=False,
    )
    assert c.status_code == 303
    doc_id = read_out(client)
    cid = sql(client, "SELECT id FROM contact")[0][0]
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE invoice_extraction SET contact_id = :c"), {"c": cid})
    assert "Bekende leverancier: <strong>Jansen Installatie</strong>" in client.get(
        f"/inbox/{doc_id}/nakijken"
    ).text


def test_suggested_account_is_preselected_and_listed_first(client):
    doc_id = read_out(client)
    suggested = account_id(client, "4999")
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE invoice_extraction_line SET account_id = :a"), {"a": suggested})
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    first_option = html.split('name="line_account_code"')[1].split("</option>")[1]
    assert 'value="4999" data-vat="NL_21" selected' in html and "4999" in first_option
    assert "Kies een rekening. Twijfel je?" not in html


def _account_options(html: str) -> str:
    return html.split('name="line_account_code"')[1].split("</select>")[0]


def test_review_account_list_only_has_purchase_accounts_plus_selected(client):
    doc_id = read_out(client)
    options = _account_options(client.get(f"/inbox/{doc_id}/nakijken").text)
    assert 'value="4210"' in options  # kosten: selectable at inkoop
    assert 'value="1300"' not in options  # not an inkoop account
    with client.app.state.engine.begin() as conn:
        conn.execute(
            text("UPDATE invoice_extraction_line SET account_id = (SELECT id FROM account WHERE code='1300')")
        )
    options = _account_options(client.get(f"/inbox/{doc_id}/nakijken").text)
    assert 'value="1300" data-vat="' in options and "selected" in options.split('value="1300"')[1].split(">")[0]


def test_review_options_carry_data_vat_and_script(client):
    doc_id = read_out(client)
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    assert '<script src="/static/js/vat-suggest.js"' in html
    assert 'value="4210" data-vat="NL_21"' in html
    assert 'value="4400" data-vat="GEEN"' in html


def test_save_review_redirects_with_notice(client):
    doc_id = read_out(client)
    r = client.post(f"/inbox/{doc_id}/nakijken", data=review_data(client), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/inbox/{doc_id}/nakijken?melding=opgeslagen"
    assert "Opgeslagen." in client.get(r.headers["location"]).text


def test_finish_review_goes_to_inbox_with_next_step(client):
    doc_id = read_out(client)
    r = client.post(
        f"/inbox/{doc_id}/nakijken", data=review_data(client, actie="klaar"), follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/inbox?melding=klaar"
    assert "Klaar met nakijken. De volgende stap is boeken." in client.get(r.headers["location"]).text
    assert sql(client, "SELECT reviewed_at FROM invoice_extraction")[0][0] is not None


@pytest.mark.parametrize("actie", ["opslaan", "klaar"])
def test_review_keeps_document_kind(client, actie):
    from dataclasses import replace

    doc_id = read_out(client, FakeExtractor(replace(INVOICE, kind="credit_note")))
    assert sql(client, "SELECT kind FROM invoice_extraction")[0][0] == "credit_note"
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    assert 'name="kind" value="credit_note"' in html
    r = client.post(
        f"/inbox/{doc_id}/nakijken",
        data=review_data(client, actie=actie, kind="credit_note"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert sql(client, "SELECT kind FROM invoice_extraction")[0][0] == "credit_note"


def test_validation_error_keeps_input_and_explains(client):
    doc_id = read_out(client)
    data = review_data(client, line_amount_excl=["abc"], invoice_number="KEEP-ME")
    r = client.post(f"/inbox/{doc_id}/nakijken", data=data)
    assert r.status_code == 422
    assert 'role="alert"' in r.text
    assert "is geen geldig bedrag" in r.text
    assert 'value="abc"' in r.text and 'value="KEEP-ME"' in r.text
    assert "Traceback" not in r.text


def test_review_line_partial(client):
    doc_id = read_out(client)
    r = client.get(f"/inbox/{doc_id}/nakijken/regel")
    assert r.status_code == 200
    assert r.text.lstrip().startswith("<tr") and 'name="line_description"' in r.text
    assert 'name="line_account_code"' in r.text and "<html" not in r.text


def test_review_of_booked_document_cannot_be_saved(client):
    doc_id = read_out(client)
    book(client, doc_id)
    r = client.post(f"/inbox/{doc_id}/nakijken", data=review_data(client))
    assert r.status_code == 422 and "al geboekt" in r.text


# --- plain language ---------------------------------------------------------------


def test_extraction_pages_are_plain_language(client):
    new_id = add_doc(client, "nieuw.pdf", PDF + b"1")
    failed_id = add_doc(client, "fout.pdf", PDF + b"2")
    use(client, FakeExtractor(error=ExtractionFailedError("Het uitlezen is niet gelukt.")))
    client.post(f"/inbox/{failed_id}/uitlezen")
    use(client, FakeExtractor(INVOICE))
    ok_id = add_doc(client, "ok.pdf", PDF + b"3")
    client.post(f"/inbox/{ok_id}/uitlezen")
    for url in (
        "/inbox",
        f"/inbox/{new_id}",
        f"/inbox/{new_id}/nakijken",
        f"/inbox/{failed_id}/nakijken",
        f"/inbox/{ok_id}/nakijken",
        f"/inbox/{ok_id}",
    ):
        assert_plain_language(client, url)


def test_review_redesign_markup_and_plain_language(client):
    from tests.web_helpers import assert_plain_language

    doc_id = read_out(client)
    flags = [{"field": "invoice_date", "level": "medium", "reason": "Controleer de datum"}]
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE invoice_extraction SET flags_json = :f"), {"f": json.dumps(flags)})
    html = assert_plain_language(client, f"/inbox/{doc_id}/nakijken")
    assert 'href="/static/css/inbox.css"' in html and 'class="breadcrumb"' in html
    assert "notice notice--warning" in html and "pill pill--warning" in html
    for heading in ("Van welke leverancier?", "Over de factuur", "Wat is er uitgegeven?", "Totalen op de factuur"):
        assert heading in html
    assert 'class="form-actions"' in html and "Klaar met nakijken" in html
    assert 'for="supplier_name"' in html


def test_review_saved_notice_is_a_status_notice(client):
    doc_id = read_out(client)
    html = client.get(f"/inbox/{doc_id}/nakijken?melding=opgeslagen").text
    assert "notice notice--success" in html and "Opgeslagen." in html
