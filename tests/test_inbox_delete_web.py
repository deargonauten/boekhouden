"""Web tests for deleting unbooked inbox documents (/inbox/{id}/verwijderen)."""

import hashlib
import re
from pathlib import Path

import pytest

from app.domain.extraction.extractors.fake import FakeExtractor
from app.domain.glossary import GLOSSARY
from app.web import extraction_routes
from app.domain.extraction.service import BackendStatus
from tests.test_extraction_web import (
    INVOICE,
    PDF,
    add_doc,
    book,
    read_out,
    sql,
    use,
)
from tests.web_helpers import assert_plain_language, visible_text

PDF2 = PDF + b"% second\n"
PDF3 = PDF + b"% third\n"


@pytest.fixture(autouse=True)
def cli_ready(monkeypatch):
    monkeypatch.setattr(
        extraction_routes, "backend_status", lambda settings: BackendStatus("claude_cli", True, "")
    )


@pytest.fixture(autouse=True)
def _clean_overrides(client):
    yield
    client.app.dependency_overrides.clear()


def file_of(client, data: bytes) -> Path:
    h = hashlib.sha256(data).hexdigest()
    return client.app.state.settings.documents_dir / h[:2] / f"{h}.pdf"


def count(client, table="document"):
    return sql(client, f"SELECT count(*) FROM {table}")[0][0]


def test_confirm_page_nieuw(client):
    doc_id = add_doc(client, "fout.pdf")
    r = client.get(f"/inbox/{doc_id}/verwijderen")
    assert r.status_code == 200
    text = visible_text(r.text)
    assert "Document verwijderen?" in text
    assert "Je staat op het punt fout.pdf te verwijderen." in re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)).replace(" .", ".")
    assert "Dit kun je niet ongedaan maken." in text
    assert "Upload het bestand later opnieuw als je je bedenkt." in text
    assert "De uitgelezen gegevens (leverancier, bedragen, regels) gaan ook verloren." not in text
    assert "Ja, verwijderen" in r.text
    assert "Annuleren" in r.text
    assert f'action="/inbox/{doc_id}/verwijderen"' in r.text
    assert GLOSSARY["verwijderen_document"].explanation in r.text


def test_confirm_page_herkend_mentions_extraction(client):
    doc_id = read_out(client)
    r = client.get(f"/inbox/{doc_id}/verwijderen")
    assert "De uitgelezen gegevens (leverancier, bedragen, regels) gaan ook verloren." in visible_text(r.text)


def test_confirm_page_geboekt_shows_storno_message_without_button(client):
    doc_id = add_doc(client)
    book(client, doc_id)
    r = client.get(f"/inbox/{doc_id}/verwijderen")
    assert r.status_code == 200
    assert "Stornoboeking maken" in r.text
    assert "Dit document is al geboekt en kan niet worden verwijderd" in r.text
    assert "Ja, verwijderen" not in r.text


def test_confirm_page_unknown_id_404(client):
    assert client.get("/inbox/999/verwijderen").status_code == 404


def test_post_deletes_document(client):
    doc_id = add_doc(client)
    path = file_of(client, PDF)
    assert path.is_file()
    r = client.post(f"/inbox/{doc_id}/verwijderen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/inbox?melding=verwijderd"
    assert not path.exists()
    assert count(client) == 0
    assert client.get(f"/inbox/{doc_id}").status_code == 404
    page = client.get(r.headers["location"])
    assert "Het document is verwijderd." in page.text
    assert "factuur.pdf" not in page.text


def test_post_herkend_removes_extraction_rows(client):
    doc_id = read_out(client)
    assert count(client, "invoice_extraction") == 1
    assert count(client, "invoice_extraction_line") == 1
    r = client.post(f"/inbox/{doc_id}/verwijderen", follow_redirects=False)
    assert r.status_code == 303
    assert count(client) == 0
    assert count(client, "invoice_extraction") == 0
    assert count(client, "invoice_extraction_line") == 0


def test_post_geboekt_is_refused(client):
    doc_id = add_doc(client)
    book(client, doc_id)
    r = client.post(f"/inbox/{doc_id}/verwijderen", follow_redirects=False)
    assert r.status_code == 409
    assert "stornoboeking" in r.text.lower()
    assert count(client) == 1
    assert file_of(client, PDF).is_file()


def test_post_unknown_id_404(client):
    assert client.post("/inbox/999/verwijderen").status_code == 404


def test_buttons_for_nieuw_herkend_not_geboekt(client):
    nieuw = add_doc(client, "a.pdf", PDF)
    herkend = add_doc(client, "b.pdf", PDF2)
    with client.app.state.engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("UPDATE document SET status = 'herkend' WHERE id = :i"), {"i": herkend})
    booked = add_doc(client, "c.pdf", PDF3)
    book(client, booked)

    listing = client.get("/inbox").text
    assert f'href="/inbox/{nieuw}/verwijderen"' in listing
    assert f'href="/inbox/{herkend}/verwijderen"' in listing
    assert f'href="/inbox/{booked}/verwijderen"' not in listing

    for doc_id, expected in ((nieuw, True), (herkend, True), (booked, False)):
        for headers in ({}, {"HX-Request": "true", "HX-Target": "inbox-drawer-body"}):
            html = client.get(f"/inbox/{doc_id}", headers=headers).text
            assert (f'href="/inbox/{doc_id}/verwijderen"' in html) is expected
            if not expected:
                assert "Dit document is geboekt en kan niet worden verwijderd." in html


def test_old_never_deleted_texts_are_gone_and_new_hint_is_used(client):
    doc_id = add_doc(client)
    hint = "Een geboekt document wordt altijd bewaard"
    rest = "Een document dat nog niet is geboekt kun je verwijderen."
    for html in (client.get("/inbox").text, client.get(f"/inbox/{doc_id}").text):
        assert "nooit verwijderd" not in html
        assert hint in html and rest in html


def test_glossary_terms():
    assert "Daarom kun je een geboekt document hier niet verwijderen." in GLOSSARY["bewaarplicht"].explanation
    term = GLOSSARY["verwijderen_document"]
    assert term.term == "Document verwijderen"


def test_pages_are_plain_language(client):
    nieuw = add_doc(client, "a.pdf", PDF)
    booked = add_doc(client, "c.pdf", PDF3)
    book(client, booked)
    assert_plain_language(client, f"/inbox/{nieuw}/verwijderen")
    assert_plain_language(client, f"/inbox/{booked}/verwijderen")
    assert_plain_language(client, f"/inbox/{booked}")


class DeletingExtractor(FakeExtractor):
    """Deletes the given documents from the database while 'extracting' (simulated race)."""

    def __init__(self, client, victims, **kw):
        super().__init__(INVOICE, **kw)
        self.client, self.victims = client, victims

    def extract(self, request):
        from sqlalchemy import text

        with self.client.app.state.engine.begin() as conn:
            for vid in self.victims:
                conn.execute(text("DELETE FROM document WHERE id = :i"), {"i": vid})
        return super().extract(request)


def test_extract_document_deleted_meanwhile_is_not_a_500(client):
    doc_id = add_doc(client)
    use(client, DeletingExtractor(client, [doc_id]))
    r = client.post(f"/inbox/{doc_id}/uitlezen")
    assert r.status_code == 404
    assert "Dit document is ondertussen verwijderd. Ga terug naar je inbox." in r.text
    assert count(client, "invoice_extraction") == 0


def test_extract_all_continues_after_deleted_document(client):
    first = add_doc(client, "a.pdf", PDF)
    second = add_doc(client, "b.pdf", PDF2)
    use(client, DeletingExtractor(client, [first]))
    r = client.post("/inbox/uitlezen-alles")
    assert r.status_code == 200
    assert "Dit document is ondertussen verwijderd. Ga terug naar je inbox." in r.text
    assert sql(client, "SELECT status FROM document WHERE id = :i", i=second)[0][0] == "herkend"
    assert count(client, "invoice_extraction") == 1


def test_review_save_for_deleted_document_is_not_a_500(client, monkeypatch):
    doc_id = read_out(client)
    from app.web import extraction_routes as routes
    from app.domain.errors import DocumentNotFoundError

    def gone(*a, **k):
        raise DocumentNotFoundError("weg")

    monkeypatch.setattr(routes, "save_review", gone)
    r = client.post(
        f"/inbox/{doc_id}/nakijken",
        data={"supplier_name": "x", "currency": "EUR", "line_description": ["a"]},
    )
    assert r.status_code == 404
    assert "Dit document is ondertussen verwijderd. Ga terug naar je inbox." in r.text


def test_claude_md_documents_the_exception():
    text = (Path(__file__).parent.parent / "CLAUDE.md").read_text()
    assert "the only exception is an unbooked inbox document" in text
    assert "Bank import files are never deleted." in text
