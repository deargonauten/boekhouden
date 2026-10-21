"""The /help page (every glossary term), the settings navigation data and is_drawer_request."""

import re
from types import SimpleNamespace

from app.domain.glossary import GLOSSARY
from app.web import is_drawer_request, templates
from app.web.navigation import SETTINGS_NAV, is_settings_active, mark_active
from tests.web_helpers import bare_term_elements


def test_help_lists_every_glossary_entry(client):
    r = client.get("/help")
    assert r.status_code == 200
    rows = re.findall(r'<tr id="term-(\w+)">', r.text)
    assert len(rows) == len(GLOSSARY)
    assert set(rows) == set(GLOSSARY)
    assert "<h1>Uitleg van termen</h1>" in r.text
    assert 'data-filter-table="#help-terms"' in r.text
    assert 'class="page-header__icon"' in r.text


def test_help_entries_lead_with_plain_dutch_then_term_in_parentheses(client):
    html = client.get("/help").text
    t = GLOSSARY["grootboek"]
    assert re.search(rf'<strong>{re.escape(t.plain)}</strong> <span class="muted">\({t.term}\)</span>', html)
    assert bare_term_elements(html) == []  # headings and labels never show a bare term


def test_help_is_reachable_from_404(client):
    assert 'href="/help"' in client.get("/bestaat-niet").text


def test_help_is_read_only(client):
    assert client.post("/help").status_code in (404, 405)


def req(headers):
    return SimpleNamespace(headers=headers)


def test_is_drawer_request_exact_match():
    assert is_drawer_request(req({"HX-Target": "boeking-drawer-body"}), "boeking-drawer")
    assert not is_drawer_request(req({"HX-Target": "body"}), "boeking-drawer")
    assert not is_drawer_request(req({}), "boeking-drawer")
    assert not is_drawer_request(req({"HX-Target": "inbox-drawer-body"}), "boeking-drawer")


def test_settings_nav_contract():
    assert [g.label for g in SETTINGS_NAV] == ["Mijn bedrijf", "Boekhouding"]
    assert [(i.label, i.path, i.term_key) for i in SETTINGS_NAV[0].items] == [
        ("Bedrijfsgegevens", "/instellingen/bedrijfsgegevens", "bedrijfsgegevens"),
    ]
    items = SETTINGS_NAV[1].items
    assert [(i.label, i.path, i.term_key) for i in items] == [
        ("Grootboek", "/instellingen/grootboek", "grootboek"),
        ("Dagboeken", "/instellingen/dagboeken", "dagboek"),
        ("Boekjaren", "/instellingen/boekjaren", "boekjaar"),
    ]
    assert is_settings_active(items[0], "/instellingen/grootboek")
    assert is_settings_active(items[0], "/instellingen/grootboek/x")
    assert not is_settings_active(items[0], "/instellingen/grootboekx")


def render_settings(path):
    src = (
        '{% extends "base_settings.html" %}'
        '{% block settings_header %}<header class="page-header"><h1>Kop</h1></header>{% endblock %}'
        "{% block settings_content %}<p>Inhoud</p>{% endblock %}"
    )
    return templates.env.from_string(src).render(current_path=path, nav_items=mark_active(path))


def test_base_settings_renders_secondary_nav_with_active_link():
    html = render_settings("/instellingen/dagboeken")
    nav = re.search(r'<nav class="settings-nav" aria-label="Instellingen">.*?</nav>', html, re.S).group(0)
    assert 'settings-nav__heading">Boekhouding<' in nav
    assert 'settings-nav__heading">Mijn bedrijf<' in nav
    assert nav.count('class="settings-nav__link"') + nav.count('class="settings-nav__link" aria') == 4
    assert nav.count('aria-current="page"') == 1
    assert re.search(r'href="/instellingen/dagboeken" aria-current="page">Dagboeken', nav)
    for key in ("bedrijfsgegevens", "grootboek", "dagboek", "boekjaar"):
        assert f'data-term="{key}"' in nav
    assert html.index("<h1>Kop</h1>") < html.index('class="settings-layout"')  # band sits above the columns
    assert '<div class="settings-content">' in html and "<p>Inhoud</p>" in html
