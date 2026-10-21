import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from app import web
from app.web.navigation import NAV_ITEMS, mark_active

PAGES = [
    ("/inbox", "Inbox"),
    ("/boeken", "Boeken"),
    ("/bank", "Bank"),
    ("/verkoop", "Verkoop"),
    ("/inkoop", "Inkoop"),
    ("/relaties", "Relaties"),
    ("/btw", "BTW"),
    ("/rapportages", "Rapportages"),
    ("/activa", "Activa"),
    ("/instellingen", "Instellingen"),
]
LABELS = [label for _, label in PAGES]


# Local fallback fixture: a minimal app with only the web contract.
# Remove once tests/conftest.py (Part A) provides the shared `client` fixture.
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(web.router)
    app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request, exc):
        if exc.status_code == 404:
            return web.not_found_response(request)
        raise exc

    return TestClient(app)


def sidebar_labels(html):
    nav = re.search(r"<nav.*?</nav>", html, re.S).group(0)
    return re.findall(r'<a [^>]*class="nav-link[^"]*"[^>]*>\s*(.*?)\s*</a>', nav, re.S)


@pytest.mark.parametrize("path,label", PAGES)
def test_page(client, path, label):
    r = client.get(path)
    assert r.status_code == 200
    assert f"<h1>{label}</h1>" in r.text
    assert "Deze pagina is nog in ontwikkeling." in r.text
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
