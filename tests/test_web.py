import re

import pytest

from app import web
from app.web.navigation import NAV_ITEMS, mark_active

# /bank (tests/test_bank_web.py), /inbox (tests/test_inbox_web.py), /boeken, /instellingen and /relaties are real pages now (tests/test_ledger_web.py, tests/test_relations_web.py).
PAGES = [
    ("/verkoop", "Verkoop"),
    ("/btw", "BTW"),
    ("/rapportages", "Rapportages"),
    ("/activa", "Activa"),
]
LABELS = [
    "Inbox", "Boeken", "Bank", "Verkoop", "Inkoop", "Relaties", "BTW",
    "Rapportages", "Activa", "Instellingen",
]


def sidebar_labels(html):
    nav = re.search(r"<nav.*?</nav>", html, re.S).group(0)
    return re.findall(r'<a [^>]*class="nav-link[^"]*"[^>]*>\s*(.*?)\s*</a>', nav, re.S)


@pytest.mark.parametrize("path,label", PAGES)
def test_page(client, path, label):
    r = client.get(path)
    assert r.status_code == 200
    assert f"<h1>{label}</h1>" in r.text
    assert "Deze pagina is nog in ontwikkeling" in r.text
    assert 'href="/inbox"' in r.text
    assert sidebar_labels(r.text) == LABELS
    assert r.text.count('aria-current="page"') == 1
    m = re.search(r'<a [^>]*aria-current="page"[^>]*>\s*(.*?)\s*</a>', r.text, re.S)
    assert m.group(1) == label
    assert f'href="{path}"' in m.group(0)
    assert "active" in m.group(0)


def test_root_redirects(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/inbox"


def test_layout_basics(client):
    html = client.get("/inbox").text
    assert '<html lang="nl"' in html
    assert 'hx-boost="true"' in html
    assert "/static/htmx.min.js" in html
    assert "/static/app.css" in html
    assert "Boekhouden" in html
    assert "http://" not in html and "https://" not in html


def test_static_served(client):
    assert client.get("/static/app.css").status_code == 200
    r = client.get("/static/htmx.min.js")
    assert r.status_code == 200 and len(r.content) > 1000


def test_unknown_path_404(client):
    r = client.get("/bestaat-niet")
    assert r.status_code == 404
    assert "Pagina niet gevonden" in r.text
    assert sidebar_labels(r.text) == LABELS
    assert 'lang="nl"' in r.text
    assert 'aria-current="page"' not in r.text


def test_active_prefix_match():
    assert [i.key for i in mark_active("/boeken/12") if i.active] == ["boeken"]
    assert not any(i.active for i in mark_active("/boekenx"))
    assert len(NAV_ITEMS) == 10


def test_help_button_on_every_page_kind(client):
    for path in ("/inbox", "/bank", "/bestaat-niet"):
        html = client.get(path).text
        assert re.search(r'<a class="help-fab" href="/help" aria-label="Uitleg over begrippen"', html), path


def test_help_page_is_not_in_the_sidebar(client):
    html = client.get("/inbox").text
    assert "Uitleg" not in sidebar_labels(html)
    nav = re.search(r"<nav.*?</nav>", html, re.S).group(0)
    assert 'href="/help"' not in nav


def test_placeholder_icon_and_help_link(client):
    html = client.get("/verkoop").text
    assert 'class="page-header__icon"' in html
    assert 'href="/help"' in html and 'href="/inbox"' in html
