"""Web tests for the controle page (/controle): redirect, checklist, 404, period switcher, read-only."""

import re
from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Document
from tests.vat.vat_helpers import Book
from tests.web_helpers import assert_plain_language

YEAR = date.today().year
Q1 = f"/controle/{YEAR}/quarter/1"
DAY = date(YEAR, 2, 10)
NOW = datetime(YEAR, 1, 1)


@pytest.fixture
def with_problems(client):
    """One manual expense without a bon and one inbox document that is not booked yet."""
    with Session(client.app.state.engine) as s:
        book = Book(s, YEAR)
        book.post([("4000", 5_000, 0), ("1210", 0, 5_000)], day=DAY, desc="Koffie", journal="BANK")
        s.add(Document(
            sha256="1" * 64, original_filename="factuur.pdf", content_type="application/pdf", size_bytes=1,
            status="nieuw", source="upload", received_at=datetime(YEAR, 2, 11, 10), created_at=NOW, updated_at=NOW,
        ))
        s.commit()
    return client


def test_controle_redirects_to_current_period(client):
    r = client.get("/controle", follow_redirects=False)
    assert r.status_code == 303
    assert re.fullmatch(rf"/controle/{date.today().year}/(quarter|month)/\d+", r.headers["location"])


def test_empty_period_is_all_fine(client):
    r = client.get(Q1)
    assert r.status_code == 200
    assert "Alles lijkt in orde" in r.text
    assert r.text.count(">Klopt<") == 5
    assert "Terug naar de btw-aangifte" in r.text and f"/btw/{YEAR}/quarter/1" in r.text


def test_page_lists_problems_with_fix_links(with_problems):
    r = with_problems.get(Q1)
    assert r.status_code == 200
    assert "2 dingen om te controleren" in r.text
    assert ">Let op<" in r.text
    assert 'href="/inbox"' in r.text
    assert "Koffie" in r.text
    assert r.text.count(">Klopt<") == 3


def test_problem_links_resolve(with_problems):
    html = with_problems.get(Q1).text
    hrefs = set(re.findall(r'href="(/(?:boeken|inbox|verkoop|bank)[^"#]*)"', html))
    assert hrefs
    for href in hrefs:
        assert with_problems.get(href).status_code == 200, href


def test_invalid_period_is_404(client):
    for path in (f"/controle/{YEAR}/quarter/5", f"/controle/{YEAR}/week/1", "/controle/abc/quarter/1"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "Pagina niet gevonden" in r.text


def test_period_switcher_crosses_year_boundary(client):
    r = client.get(Q1)
    assert f'href="/controle/{YEAR - 1}/quarter/4"' in r.text
    assert f'href="/controle/{YEAR}/quarter/2"' in r.text
    r = client.get(f"/controle/{YEAR}/quarter/4")
    assert f'href="/controle/{YEAR + 1}/quarter/1"' in r.text


def test_nav_item_is_active_on_subpath(client):
    html = client.get(Q1).text
    assert re.search(r'class="nav-link active"[^>]*aria-current="page">\s*Controle', html)


def test_get_does_not_write(with_problems):
    def counts():
        with Session(with_problems.app.state.engine) as s:
            return [s.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in
                    ("journal_entry", "journal_line", "document", "bank_transaction", "vat_return")]

    before = counts()
    with_problems.get(Q1)
    with_problems.get("/controle", follow_redirects=False)
    assert counts() == before


@pytest.mark.parametrize("fixture", ["client", "with_problems"])
def test_plain_language(request, fixture):
    c = request.getfixturevalue(fixture)
    assert_plain_language(c, Q1)
