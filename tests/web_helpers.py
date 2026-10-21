"""Helpers to enforce plain-language screens. Later features add their pages to
PAGES in tests/test_plain_language.py and call assert_plain_language().
"""

import html as htmllib
import re

from app.domain.glossary import Term, all_terms

FLAGS = re.S | re.I
_TOOLTIP = re.compile(r'<span[^>]*role="tooltip"[^>]*>.*?</span>', FLAGS)
_BLOCKS = ("script", "style", "td", "dd", "option", "aside", "nav")

# Bare glossary words that may stand alone: they are navigation labels or page
# names whose plain-language explanation is the sidebar sub-line / title.
BARE_OK = {"boeken", "bank", "inbox", "relaties", "rapportages", "btw", "activa", "verkoop", "inkoop"}


def strip_cells(html: str) -> str:
    """Remove everything that is data or chrome: script, style, <td>/<dd> data cells, <option>,
    tooltip text, the sidebar and navigation bars."""
    html = _TOOLTIP.sub("", html)
    for tag in _BLOCKS:
        html = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", html, flags=FLAGS)
    return html


def visible_text(html: str) -> str:
    """Visible text of the page outside data cells, options and tooltips."""
    text = re.sub(r"<[^>]+>", " ", strip_cells(html))
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def detect_patterns(term: Term) -> list[str]:
    return list(term.detect) or [rf"\b{re.escape(term.term)}\b"]


def missing_term_keys(html: str, allow: set[str] = frozenset()) -> list[str]:
    text = visible_text(html)
    missing = []
    for term in all_terms():
        if term.key in allow or f'data-term="{term.key}"' in html:
            continue
        if any(re.search(p, text, re.I) for p in detect_patterns(term)):
            missing.append(term.key)
    return missing


def bare_term_elements(html: str, allow: set[str] = BARE_OK) -> list[str]:
    """label/th/h1-3/button whose whole text is a bare glossary term, without an
    info marker or a parenthesised plain phrase."""
    terms = {t.term.lower() for t in all_terms()} - allow
    html = _TOOLTIP.sub("", html)
    html = re.sub(r"<(aside|script|style)\b[^>]*>.*?</\1>", " ", html, flags=FLAGS)
    bare = []
    for m in re.finditer(r"<(label|th|h[1-3]|button)\b[^>]*>(.*?)</\1>", html, FLAGS):
        inner = m.group(2)
        if "data-term=" in inner:
            continue
        text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if "(" in text:
            continue
        if text.lower() in terms:
            bare.append(text)
    return bare


def assert_plain_language(client, url: str, allow: set[str] = frozenset()) -> str:
    """Fetch url and assert every glossary term has an info marker and no bare
    term is used as a label. Returns the HTML."""
    response = client.get(url)
    assert response.status_code == 200, f"{url}: status {response.status_code}"
    html = response.text
    missing = missing_term_keys(html, set(allow))
    assert not missing, f"{url}: term(s) without info icon: {missing}"
    bare = bare_term_elements(html)
    assert not bare, f"{url}: bare bookkeeping term(s) without plain wording: {bare}"
    return html
