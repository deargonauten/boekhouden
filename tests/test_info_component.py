import re

import pytest
from jinja2 import UndefinedError

from app.domain.glossary import get_term
from app.web import templates
from app.web.navigation import NAV_ITEMS, mark_active

IMPORT = '{% from "partials/_info.html" import info, term_label with context %}'


def render(src: str) -> str:
    return templates.env.from_string(IMPORT + src).render()


def test_info_markup():
    out = render('{{ info("debet") }}')
    t = get_term("debet")
    assert 'data-term="debet"' in out
    assert 'role="tooltip"' in out
    assert t.explanation in out
    assert 'aria-label="Uitleg: Debet"' in out
    describedby = re.search(r'aria-describedby="([^"]+)"', out).group(1)
    assert f'id="{describedby}"' in out


def test_ids_unique_for_same_key():
    out = render('{{ info("debet") }}{{ info("debet") }}')
    ids = re.findall(r'role="tooltip" id="([^"]+)"', out)
    assert len(ids) == 2 and ids[0] != ids[1]


def test_unknown_key_raises():
    with pytest.raises((KeyError, UndefinedError)):
        render('{{ info("bestaat_niet") }}')
    with pytest.raises((KeyError, UndefinedError)):
        render('{{ term_label("bestaat_niet") }}')


def test_term_label_plain_first_then_term():
    out = render('{{ term_label("dagboek") }}')
    t = get_term("dagboek")
    assert out.index(t.plain) < out.index("(Dagboek)") < out.index('data-term="dagboek"')


def test_term_label_plain_override():
    out = render('{{ term_label("dagboek", "In welk dagboek?") }}')
    assert "In welk dagboek? (Dagboek)" in out


def test_nav_term_keys():
    keys = {i.label: i.term_key for i in NAV_ITEMS}
    assert keys == {
        "Inbox": "inbox", "Boeken": "boeking", "Bank": "bank", "Verkoop": "debiteuren",
        "Inkoop": "crediteuren", "Relaties": "relaties", "BTW": "btw",
        "Rapportages": "rapportages", "Activa": "activa", "Instellingen": None,
    }
    assert all(i.term_key == n.term_key for i, n in zip(NAV_ITEMS, mark_active("/")))


def test_sidebar_sub_lines_and_titles(client):
    html = client.get("/inbox").text
    nav = re.search(r"<nav.*?</nav>", html, re.S).group(0)
    for item in NAV_ITEMS:
        if not item.term_key:
            continue
        t = get_term(item.term_key)
        assert f'<span class="nav-sub">{t.plain}</span>' in nav
        assert f'title="{t.explanation}"' in nav
