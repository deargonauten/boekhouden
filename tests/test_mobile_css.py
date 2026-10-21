"""Regression guards for the 375px layout (no sideways page scroll, one-line search box).

Real measurement needs a browser; these assert the CSS rules that fix the measured overflow."""

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "app/web/static/app.css").read_text()


def mobile_block() -> str:
    m = re.search(r"@media \(max-width: 899px\) \{\n  \.app-shell.*?\n\}\n", CSS, re.S)
    assert m, "mobile @media block not found"
    return m.group(0)


def test_content_does_not_widen_page_on_mobile():
    block = mobile_block()
    assert re.search(r"\.content \{ overflow-x: clip; \}", block)
    assert re.search(r"\.card--flush \{ contain: paint; \}", block)


def test_mobile_search_has_no_flex_basis_height():
    # .toolbar becomes a column on mobile; a 16rem flex-basis would turn into height.
    assert re.search(r"\.toolbar__search \{ max-width: none; flex: 0 0 auto; \}", CSS)
