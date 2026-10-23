"""The controle banner on the BTW-aangifte and indienen pages: advisory, never blocking."""

from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.models import Document
from tests.vat.vat_helpers import set_company

YEAR = date.today().year
Q1 = f"/btw/{YEAR}/quarter/1"
LINK = f"/controle/{YEAR}/quarter/1"
NOW = datetime(YEAR, 1, 1, 12)


@pytest.fixture(autouse=True)
def company(client):
    with Session(client.app.state.engine) as s:
        set_company(s)
        s.commit()


def _add_inbox_doc(client):
    with Session(client.app.state.engine) as s:
        s.add(Document(
            sha256="1" * 64, original_filename="factuur.pdf", content_type="application/pdf", size_bytes=1,
            status="nieuw", source="upload", received_at=datetime(YEAR, 2, 1, 10), created_at=NOW, updated_at=NOW,
        ))
        s.commit()


def test_return_page_banner_ok(client):
    r = client.get(Q1)
    assert r.status_code == 200
    assert "Alles lijkt in orde" in r.text
    assert LINK in r.text


def test_return_page_banner_with_problem(client):
    _add_inbox_doc(client)
    r = client.get(Q1)
    assert "1 ding om te controleren" in r.text
    assert LINK in r.text
    assert "Alles lijkt in orde" not in r.text


def test_banner_sits_above_controleer_dit_card(client):
    _add_inbox_doc(client)
    text = client.get(Q1).text
    assert "Klopt dit?" in text
    if "Controleer dit" in text:
        assert text.index(LINK) < text.index("Controleer dit")


def test_filed_return_has_no_banner(client):
    r = client.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(Q1).text
    assert "Ingediend" in page
    assert LINK not in page


def test_confirm_page_banner_and_sentence(client):
    _add_inbox_doc(client)
    r = client.get(f"{Q1}/indienen")
    assert r.status_code == 200
    assert LINK in r.text
    assert "Je kunt toch indienen als je zeker weet dat het klopt." in r.text


def test_filing_works_with_warnings(client):
    _add_inbox_doc(client)
    r = client.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()}, follow_redirects=False)
    assert r.status_code == 303
    assert "Ingediend" in client.get(Q1).text


@pytest.mark.parametrize("suffix", ["", "/indienen"])
def test_banner_failure_does_not_break_page(client, monkeypatch, suffix):
    def boom(*a, **k):
        raise RuntimeError("kapot")

    monkeypatch.setattr("app.web.btw_routes.checks.run_checks", boom)
    r = client.get(Q1 + suffix)
    assert r.status_code == 200
    assert LINK not in r.text
    assert "kapot" not in r.text
    if suffix:
        assert "Dit kun je niet terugdraaien." in r.text
