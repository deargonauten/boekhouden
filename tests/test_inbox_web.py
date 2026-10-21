"""Web tests for the document inbox (/inbox*)."""

import hashlib
import re
from datetime import datetime

import pytest
from sqlalchemy import text

from tests.web_helpers import visible_text

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PDF2 = PDF + b"% second\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TXT = b"dit is geen factuur"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stored(client, data: bytes, ext: str):
    h = sha(data)
    return client.app.state.settings.documents_dir / h[:2] / f"{h}.{ext}"


def upload(client, *files):
    return client.post(
        "/inbox/upload",
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
    )


def rows(client, sql="SELECT id, original_filename, status FROM document ORDER BY id"):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(sql)).all()


def set_status(client, doc_id, status, entry_id=None):
    with client.app.state.engine.begin() as conn:
        conn.execute(
            text("UPDATE document SET status = :s, journal_entry_id = :e WHERE id = :i"),
            {"s": status, "e": entry_id, "i": doc_id},
        )


def test_empty_state(client):
    r = client.get("/inbox")
    assert r.status_code == 200
    assert "Je inbox is leeg." in r.text
    assert "Factuur of bon toevoegen" in r.text
    assert "Dit onderdeel wordt later gebouwd" not in r.text


def test_root_still_redirects_to_inbox(client):
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/inbox"


def test_upload_form_is_a_single_action(client):
    html = client.get("/inbox").text
    form = re.search(r'<form[^>]*action="/inbox/upload".*?</form>', html, re.S).group(0)
    assert 'enctype="multipart/form-data"' in form
    assert 'method="post"' in form
    assert re.search(r'<input[^>]*type="file"[^>]*multiple', form) or re.search(
        r'<input[^>]*multiple[^>]*type="file"', form
    )
    assert ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/*" in form
    assert "maximaal 20 MB per bestand" in form
    assert "Toevoegen aan inbox" in form
    # one input, one button: nothing else to fill in
    assert len(re.findall(r"<input\b", form)) == 1
    assert len(re.findall(r"<(?:select|textarea)\b", form)) == 0


def test_upload_single_pdf(client):
    r = upload(client, ("factuur.pdf", PDF))
    assert r.status_code == 200
    assert "factuur.pdf is toegevoegd aan je inbox." in r.text
    assert stored(client, PDF, "pdf").read_bytes() == PDF
    assert [row.original_filename for row in rows(client)] == ["factuur.pdf"]
    listing = client.get("/inbox").text
    assert "factuur.pdf" in listing
    assert "PDF" in listing
    assert "Upload" in listing


def test_multi_upload_good_duplicate_and_bad(client):
    upload(client, ("a.pdf", PDF))
    r = upload(client, ("b.png", PNG), ("a-again.pdf", PDF), ("notitie.txt", TXT))
    assert r.status_code == 200
    assert "b.png is toegevoegd aan je inbox." in r.text
    assert "a-again.pdf staat al in je inbox" in r.text
    assert "Het is niet nog een keer opgeslagen." in r.text
    assert "notitie.txt:" in r.text
    assert "Dit bestandstype kan niet worden verwerkt." in r.text
    assert len(rows(client)) == 2
    assert stored(client, PNG, "png").exists()


def test_duplicate_message_links_to_existing(client):
    upload(client, ("a.pdf", PDF))
    r = upload(client, ("kopie.pdf", PDF))
    assert r.status_code == 200
    first_id = rows(client)[0].id
    assert f'href="/inbox/{first_id}"' in r.text
    assert "Bekijk het bestaande document" in r.text
    assert "geupload op" in r.text and "status Nieuw" in r.text
    assert len(rows(client)) == 1


def test_identical_files_in_one_request(client):
    r = upload(client, ("x.pdf", PDF), ("y.pdf", PDF))
    assert r.status_code == 200
    assert "x.pdf is toegevoegd aan je inbox." in r.text
    assert "y.pdf staat al in je inbox" in r.text
    assert len(rows(client)) == 1


def test_all_rejected_is_422(client):
    r = upload(client, ("a.txt", TXT), ("leeg.pdf", b""))
    assert r.status_code == 422
    assert "Dit bestandstype kan niet worden verwerkt." in r.text
    assert "Dit bestand is leeg. Kies een ander bestand." in r.text
    assert rows(client) == []


def test_no_files_is_422(client):
    r = client.post("/inbox/upload", data={})
    assert r.status_code == 422
    assert "Je hebt nog geen bestand gekozen." in r.text
    r = client.post(
        "/inbox/upload", files=[("files", ("", b"", "application/octet-stream"))]
    )
    assert r.status_code == 422
    assert "Je hebt nog geen bestand gekozen." in r.text


def test_oversize_file_is_rejected_without_reading_everything(client, monkeypatch):
    from app.domain.documents import validation

    monkeypatch.setattr(validation, "MAX_DOCUMENT_BYTES", 100)
    r = upload(client, ("groot.pdf", PDF + b"x" * 500))
    assert r.status_code == 422
    assert "groot.pdf:" in r.text
    assert "Dit bestand is te groot" in r.text
    assert rows(client) == []


def test_partial_success_is_committed(client):
    r = upload(client, ("bad.txt", TXT), ("ok.pdf", PDF))
    assert r.status_code == 200
    assert len(rows(client)) == 1


def test_filenames_are_escaped(client):
    r = upload(client, ('<script>alert(1)</script>.pdf', PDF))
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_filter_counts_and_unknown_value(client):
    upload(client, ("a.pdf", PDF), ("b.png", PNG), ("c.jpg", JPEG))
    set_status(client, 2, "herkend")
    html = client.get("/inbox").text
    text_ = visible_text(html)
    assert "Alle (3)" in text_ and "Nieuw (2)" in text_
    assert "Herkend (1)" in text_ and "Geboekt (0)" in text_
    only = client.get("/inbox?status=herkend").text
    assert "b.png" in only and "a.pdf" not in only
    assert "a.pdf" in client.get("/inbox?status=onzin").text
    assert "Geen documenten met deze status." in client.get("/inbox?status=geboekt").text


def test_list_newest_first(client):
    upload(client, ("eerste.pdf", PDF))
    upload(client, ("tweede.png", PNG))
    html = client.get("/inbox").text
    assert html.index("tweede.png") < html.index("eerste.pdf")


def test_list_is_capped_with_note(client, monkeypatch):
    from app.web import inbox_routes

    monkeypatch.setattr(inbox_routes, "LIST_LIMIT", 1)
    upload(client, ("a.pdf", PDF), ("b.png", PNG))
    html = client.get("/inbox").text
    assert "b.png" in html and "a.pdf" not in html
    assert "nieuwste" in html


def test_detail_page_pdf(client):
    upload(client, ("factuur.pdf", PDF))
    r = client.get("/inbox/1")
    assert r.status_code == 200
    assert "factuur.pdf" in r.text
    assert "Nog niet verwerkt." in r.text
    assert sha(PDF) in r.text or sha(PDF)[:12] in r.text
    assert "Vingerafdruk van het bestand" in r.text
    assert "Open origineel bestand" in r.text
    assert re.search(r'<iframe[^>]*src="/inbox/1/bestand"', r.text)
    assert "Later kun je hier" not in r.text


def test_detail_page_image_uses_img(client):
    upload(client, ("foto.png", PNG))
    assert re.search(r'<img[^>]*src="/inbox/1/bestand"', client.get("/inbox/1").text)


def test_detail_booked_links_to_entry(client):
    upload(client, ("a.pdf", PDF))
    client.post("/instellingen/boekjaren", data={"year": datetime.now().year})
    journal = rows(client, "SELECT id FROM journal WHERE code = 'MEM'")[0].id
    acc = [r.id for r in rows(client, "SELECT id FROM account WHERE code IN ('4200','1210') ORDER BY code")]
    r = client.post(
        "/boeken/nieuw",
        data={
            "journal_id": str(journal),
            "booking_date": datetime.now().date().isoformat(),
            "description": "x",
            "reference": "",
            "line_account": [str(acc[1]), str(acc[0])],
            "line_debit": ["10,00", ""],
            "line_credit": ["", "10,00"],
            "line_vat": ["", ""],
            "line_description": ["", ""],
        },
        follow_redirects=False,
    )
    entry_id = int(r.headers["location"].rsplit("/", 1)[1])
    set_status(client, 1, "geboekt", entry_id)
    html = client.get("/inbox/1").text
    assert f'href="/boeken/{entry_id}"' in html
    assert "Nog niet verwerkt." not in html


def test_detail_unknown_id_is_404(client):
    assert client.get("/inbox/999").status_code == 404
    assert client.get("/inbox/999/bestand").status_code == 404


def test_file_view_headers(client):
    upload(client, ("mijn factuur.pdf", PDF))
    r = client.get("/inbox/1/bestand")
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    cd = r.headers["content-disposition"]
    assert cd.startswith("inline;") and "filename*=UTF-8''mijn%20factuur.pdf" in cd


def test_file_view_image_content_type(client):
    upload(client, ("foto.png", PNG))
    assert client.get("/inbox/1/bestand").headers["content-type"].startswith("image/png")


def test_missing_file_on_disk_shows_integrity_message(client):
    upload(client, ("a.pdf", PDF))
    p = stored(client, PDF, "pdf")
    p.chmod(0o644)
    p.unlink()
    r = client.get("/inbox/1/bestand")
    assert r.status_code == 500
    assert "Het bestand ontbreekt op schijf. Herstel data/documents uit je back-up." in r.text
    d = client.get("/inbox/1")
    assert d.status_code == 200  # detail page itself still works


@pytest.mark.parametrize(
    "method,url",
    [
        ("delete", "/inbox/1"),
        ("post", "/inbox/1/verwijderen"),
        ("post", "/inbox/1/delete"),
        ("delete", "/inbox/1/bestand"),
    ],
)
def test_no_delete_routes(client, method, url):
    upload(client, ("a.pdf", PDF))
    assert getattr(client, method)(url).status_code in (404, 405)
    assert len(rows(client)) == 1
    assert stored(client, PDF, "pdf").exists()


def test_no_status_change_route(client):
    upload(client, ("a.pdf", PDF))
    for url in ("/inbox/1/status", "/inbox/1/herkend", "/inbox/1/geboekt"):
        assert client.post(url).status_code in (404, 405)
    assert rows(client)[0].status == "nieuw"


def test_html_in_upload_filename_in_detail_is_escaped(client):
    upload(client, ("<b>x</b>.pdf", PDF))
    assert "<b>x</b>" not in client.get("/inbox/1").text
