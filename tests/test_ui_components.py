"""Design-system macros (partials/_ui.html), sidebar and base layout."""

import re
from pathlib import Path

import pytest

from app.domain.glossary import get_term
from app.web import templates
from app.web.navigation import GROUP_LABELS, NAV_ITEMS, mark_active

IMPORT = (
    '{% from "partials/_ui.html" import page_header, tabs, toolbar_search, pill, pager,'
    " empty_state, notice, error_box, icon, row_menu, stat_cards, segmented, drawer, modal, dropzone with context %}"
)
STATIC = Path(__file__).parent.parent / "app" / "web" / "static"


def render(src: str, **ctx) -> str:
    return templates.env.from_string(IMPORT + src).render(**ctx)


def hrefs(html: str) -> list[str]:
    return [h.replace("&amp;", "&") for h in re.findall(r'href="([^"]+)"', html)]


# --- pager -------------------------------------------------------------------


def test_pager_total_zero_renders_nothing():
    assert render('{{ pager(1, 50, 0, "/boeken") }}').strip() == ""


def test_pager_single_page_shows_count_only():
    out = render('{{ pager(1, 50, 14, "/boeken", noun="boekingen") }}')
    assert "Toont 1-14 van 14 boekingen" in out
    assert 'aria-label="Paginering"' in out
    assert "Vorige" not in out and "Volgende" not in out


def test_pager_middle_page_count_current_and_ellipsis():
    out = render('{{ pager(5, 10, 200, "/boeken") }}')
    assert "Toont 41-50 van 200 resultaten" in out
    assert out.count('aria-current="page"') == 1
    assert re.search(r'aria-current="page">5</a>', out) or re.search(r'aria-label="Pagina 5" aria-current', out)
    assert "&hellip;" in out
    assert out.count("&hellip;") == 2  # gap after 1 and before 20
    for n in (1, 4, 5, 6, 20):
        assert f'aria-label="Pagina {n}"' in out
    assert 'aria-label="Pagina 10"' not in out
    assert "Vorige" in out and "Volgende" in out


def test_pager_first_page_disables_previous_and_page_1_has_no_page_param():
    out = render('{{ pager(1, 10, 35, "/boeken") }}')
    assert 'aria-disabled="true"' in out and "Vorige" in out
    assert "/boeken?page=2" in hrefs(out)
    assert "/boeken" in hrefs(out)  # page 1 link


def test_pager_last_page_and_clamping():
    out = render('{{ pager(999, 10, 35, "/boeken") }}')
    assert "Toont 31-35 van 35 resultaten" in out
    assert out.count('aria-current="page"') == 1
    assert 'rel="next"' not in out
    assert "Toont 1-10 van 35" in render('{{ pager(-3, 10, 35, "/boeken") }}')


def test_pager_preserves_params_and_drops_empty():
    out = render(
        '{{ pager(2, 10, 100, "/boeken", {"q": "a b&c", "dagboek": 3, "leeg": ""}) }}'
    )
    links = hrefs(out)
    assert "/boeken?q=a+b%26c&dagboek=3&page=3" in links
    assert "/boeken?q=a+b%26c&dagboek=3" in links  # page 1
    assert not any("leeg" in h for h in links)


# --- tabs, pill, header ------------------------------------------------------


def test_tabs_aria_current_only_on_active_and_count_and_info():
    out = render(
        '{{ tabs([("Alle", "/x", True, 5), ("Nieuw", "/x?status=nieuw", False, 0, "inbox")], "Status") }}'
    )
    assert out.count('aria-current="page"') == 1
    assert re.search(r'<a href="/x" aria-current="page">Alle <span class="tab__count">5</span>', out)
    assert '<span class="tab__count">0</span>' in out  # a zero count still renders
    assert 'data-term="inbox"' in out
    assert 'aria-label="Status"' in out and 'class="tabs"' in out


@pytest.mark.parametrize("tone", ["neutral", "info", "success", "warning", "danger"])
def test_pill_tones(tone):
    out = render('{{ pill("Open", "%s", "Uitleg") }}' % tone)
    assert f'class="pill pill--{tone}"' in out
    assert 'title="Uitleg"' in out and ">Open<" in out


def test_page_header_breadcrumb_cta_term_and_lead():
    out = render(
        '{{ page_header("Boeken", [("Boeken", "/boeken"), ("Nieuwe boeking", None)],'
        ' "Nieuwe boeking", "/boeken/nieuw", term="dagboek", lead="Uitleg") }}'
    )
    assert "<h1>Boeken</h1>" in out
    assert '<a href="/boeken">Boeken</a>' in out
    assert '<span class="breadcrumb__current">Nieuwe boeking</span>' in out
    assert "/boeken/nieuw" not in [h for h in hrefs(out) if h != "/boeken/nieuw"]
    assert re.search(r'<a class="btn" href="/boeken/nieuw">.*Nieuwe boeking</a>', out, re.S)
    assert 'data-term="dagboek"' in out
    assert "Uitleg" in out


def test_page_header_last_breadcrumb_is_not_a_link_even_with_href():
    out = render('{{ page_header("Titel", [("Sectie", "/s"), ("Nu", "/nu")]) }}')
    assert 'href="/nu"' not in out and 'href="/s"' in out


def test_page_header_call_slot_and_no_cta():
    out = render('{% call page_header("T") %}<b>extra</b>{% endcall %}')
    assert "<b>extra</b>" in out and 'class="btn"' not in out
    assert "page-header__actions" not in render('{{ page_header("T") }}')


# --- other macros ------------------------------------------------------------


def test_empty_state():
    out = render('{{ empty_state("Niets", "Voeg iets toe.", "Toevoegen", "/nieuw") }}')
    assert "Niets" in out and "Voeg iets toe." in out
    assert '<a class="btn" href="/nieuw">Toevoegen</a>' in out
    assert 'class="empty"' in out
    assert "<a " not in render('{{ empty_state("Niets", "Tekst") }}')


def test_notice_and_error_box():
    out = render('{{ notice("Opgeslagen", "success") }}')
    assert 'role="status"' in out and "notice--success" in out and "Opgeslagen" in out
    assert 'role="alert"' in render('{{ error_box("Fout") }}')
    lst = render('{{ error_box(["a", "b"]) }}')
    assert lst.count("<li>") == 2 and 'role="alert"' in lst


def test_toolbar_search_form():
    out = render('{{ toolbar_search("/boeken", "ab\\"c", "Zoek boeking", {"dagboek": 2, "leeg": ""}) }}')
    assert 'method="get"' in out and 'action="/boeken"' in out
    assert 'type="search"' in out and 'name="q"' in out
    assert 'value="ab&#34;c"' in out
    assert 'hx-boost="false"' in out
    assert '<input type="hidden" name="dagboek" value="2">' in out
    assert "leeg" not in out
    assert "<svg" in out


def test_icon_known_names_render_and_unknown_raises():
    names = (
        "plus search filter edit archive restore lock check x chevron-down chevron-left chevron-right "
        "more inbox book bank receipt users percent chart box settings file upload alert info"
    ).split()
    for name in names:
        out = render('{{ icon("%s", 20) }}' % name)
        assert 'aria-hidden="true"' in out and 'stroke="currentColor"' in out
        assert 'width="20"' in out and "<path" in out or "<circle" in out
    with pytest.raises(ValueError, match="Onbekend icoon: bestaat-niet"):
        render('{{ icon("bestaat-niet") }}')


def test_nav_icons_are_valid_icon_names():
    for item in NAV_ITEMS:
        assert render('{{ icon(name) }}', name=item.icon)


def test_row_menu():
    out = render('{% call row_menu("Meer acties") %}<a href="/x">Open</a>{% endcall %}')
    assert '<details class="menu">' in out
    assert 'aria-label="Meer acties"' in out and 'href="/x"' in out


# --- sidebar and base layout -------------------------------------------------


def nav_html(client, path="/boeken"):
    html = client.get(path).text
    return html, re.search(r"<nav aria-label=\"Hoofdmenu\">.*?</nav>", html, re.S).group(0)


def test_sidebar_groups_labels_and_order(client):
    _, nav = nav_html(client)
    labels = re.findall(r'class="nav-group-label">([^<]+)<', nav)
    assert labels == list(GROUP_LABELS.values())
    assert labels == ["Verwerken", "Verkoop en inkoop", "Aangifte en overzicht"]
    order = [nav.index(f">{i.label}</a>") for i in NAV_ITEMS]
    assert order == sorted(order)
    assert nav.index("Instellingen") > nav.index("Activa")
    assert 'class="nav-group--pinned nav-footer"' in nav  # Instellingen: footer row
    assert nav.index("nav-footer") > nav.index(">Activa</a>")


def test_sidebar_active_item_and_sub_lines(client):
    html, nav = nav_html(client, "/boeken/nieuw")
    assert nav.count('aria-current="page"') == 1
    assert re.search(r'class="nav-link active"[^>]*aria-current="page">Boeken</a>', nav)
    for item in NAV_ITEMS:
        assert item.icon
        if item.term_key:
            t = get_term(item.term_key)
            assert f'<span class="nav-sub">{t.plain}</span>' in nav
            assert f'title="{item.label}: {t.explanation}"' in nav
    assert nav.count("<svg") == len(NAV_ITEMS)


def test_mark_active_keeps_icon():
    marked = mark_active("/relaties")
    assert [m.icon for m in marked] == [i.icon for i in NAV_ITEMS]
    assert [m.key for m in marked if m.active] == ["relaties"]


def test_base_layout_accessibility_and_no_external_urls(client):
    html = client.get("/bank").text
    assert '<html lang="nl">' in html
    assert re.search(r'<body[^>]*>\s*<a class="skip-link" href="#main">Naar de inhoud</a>', html)
    assert '<main class="content" id="main"' in html
    assert "/static/app.js" in html and "/static/app.css" in html
    assert "http://" not in html and "https://" not in html
    assert 'data-nav-toggle' in html and 'aria-expanded="false"' in html
    assert html.count("<h1>") == 1


@pytest.mark.parametrize("path", ["/bank", "/bestaat-niet"])
def test_placeholder_and_404_use_page_header_and_empty_state(client, path):
    html = client.get(path).text
    assert 'class="page-header"' in html and 'aria-label="Kruimelpad"' in html
    assert 'class="empty"' in html and 'href="/inbox"' in html


def test_static_assets_contract():
    css = (STATIC / "app.css").read_text()
    for token in (
        "--bg --surface --surface-2 --border --border-strong --fg --muted --primary --primary-hover "
        "--primary-soft --primary-fg --success --success-soft --warning --warning-soft --danger "
        "--danger-soft --info-soft --font --text-xs --text-sm --text --text-lg --text-xl --text-2xl "
        "--space-1 --space-8 --radius-sm --radius --radius-lg --radius-pill --shadow-sm --shadow-md "
        "--sidebar-width --content-max --focus-ring --nav-active-bg --nav-active-fg --band-bg --bar-success "
        "--bar-warning --text-3xl --sidebar-width-collapsed --settings-nav-width --drawer-width"
    ).split():
        assert f"{token}:" in css, token
    # no hard-coded hex colors outside the two token blocks
    body = re.sub(r":root[^{]*\{[^}]*\}", "", css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body)
    js = (STATIC / "app.js").read_text()
    assert len(js.splitlines()) < 260
    assert "http" not in js

# --- restyle: header band, stat cards, segmented, drawer, modal, dropzone ----


def test_page_header_icon_and_tabs_inside_band():
    out = render(
        '{{ page_header("Boeken", icon_name="book", tab_items=[("Alle", "/b", True, 3), ("MEM", "/b?d=1", False)],'
        ' tab_label="Dagboeken") }}'
    )
    assert re.search(r'<span class="page-header__icon"><svg', out)
    assert out.index("page-header__icon") < out.index("<h1>Boeken</h1>")
    band = re.search(r'<header class="page-header">(.*)</header>', out, re.S).group(1)
    assert 'class="page-header__tabs"' in band and 'aria-label="Dagboeken"' in band
    assert band.count('aria-current="page"') == 1


def test_page_header_tab_label_defaults_to_title_and_old_call_unchanged():
    out = render('{{ page_header("Relaties", tab_items=[("Alle", "/r", True)]) }}')
    assert 'aria-label="Relaties"' in out
    old = render('{{ page_header("Boeken", [("Boeken", None)]) }}')
    assert "page-header__icon" not in old and "page-header__tabs" not in old and "<h1>Boeken</h1>" in old


def test_stat_cards_two_cells_tone_and_term():
    cards = [
        {"title": "Te verwerken", "term": "inbox", "cells": [
            {"label": "Nieuw", "value": "3", "tone": "warning", "href": "/inbox?status=nieuw"},
            {"label": "Herkend", "value": "1", "tone": None, "href": None}]},
        {"title": "Klaar", "term": None, "cells": [
            {"label": "Geboekt", "value": "7", "tone": "success", "href": None},
            {"label": "Totaal", "value": "11", "tone": None, "href": None}]},
    ]
    out = render("{{ stat_cards(cards) }}", cards=cards)
    assert out.count('class="stat-card"') == 2
    assert len(re.findall(r'class="stat-cell[ "]', out)) == 4
    assert "stat-cell--warning" in out and "stat-cell--success" in out and "stat-cell--danger" not in out
    assert 'data-term="inbox"' in out and out.count("data-term=") == 1
    assert '<a href="/inbox?status=nieuw">3</a>' in out
    assert "Te verwerken" in out and "Klaar" in out


def test_segmented_single_aria_current_and_term():
    out = render(
        '{{ segmented([("Actieve relaties", "/r", True), ("Ook gearchiveerd", "/r?gearchiveerd=1", False, "relaties")], "Weergave") }}'
    )
    assert out.count('aria-current="page"') == 1
    assert re.search(r'<a href="/r" aria-current="page">Actieve relaties</a>', out)
    assert 'aria-label="Weergave"' in out and 'data-term="relaties"' in out
    assert "segmented--small" in render('{{ segmented([("A", "/a", True)], "X", small=True) }}')


def test_drawer_empty_shell_and_aria():
    out = render('{% call drawer("boeking-drawer", "Boeking", "boeking") %}Laden...{% endcall %}')
    assert re.search(
        r'<aside class="drawer" id="boeking-drawer" role="dialog" aria-modal="true" aria-labelledby="boeking-drawer-title"[^>]* hidden>',
        out,
    )
    assert 'id="boeking-drawer-title"' in out
    assert '<div class="drawer__body" id="boeking-drawer-body">Laden...</div>' in out
    assert 'aria-label="Sluiten"' in out and 'class="drawer-scrim"' in out
    assert 'data-term="boeking"' in out
    assert 'id="x-body"></div>' in render('{{ drawer("x", "Y") }}')


def test_modal_dialog_and_open_on_load_only_when_asked():
    closed = render('{% call modal("upload", "Bestand toevoegen") %}Formulier{% endcall %}')
    assert '<dialog class="modal" id="upload" aria-labelledby="upload-title">' in closed
    assert "data-open-on-load" not in closed and "Formulier" in closed
    assert "data-modal-close" in closed and 'aria-label="Sluiten"' in closed
    opened = render('{% call modal("upload", "Bestand toevoegen", open=True) %}x{% endcall %}')
    assert "data-open-on-load" in opened


def test_dropzone_native_file_input_and_multiple_toggle():
    out = render('{{ dropzone("files", ".pdf,image/*", "Bestanden kiezen", "PDF of foto.") }}')
    assert re.search(r'<label class="dropzone">\s*<input[^>]*type="file"[^>]*name="files"[^>]*accept="\.pdf,image/\*"[^>]* multiple', out)
    assert "Klik om bestanden toe te voegen of sleep ze hierheen." in out and "PDF of foto." in out
    single = render('{{ dropzone("f", ".pdf", "Kies", "", multiple=False) }}')
    assert " multiple" not in single and "een bestand" in single


def test_pager_sticky_variant_keeps_text():
    out = render('{{ pager(1, 10, 35, "/boeken", sticky=True) }}')
    assert 'class="pager pager--sticky"' in out and "Toont 1-10 van 35 resultaten" in out
    assert 'class="pager"' in render('{{ pager(1, 10, 35, "/boeken") }}')


def test_new_icon_names_render():
    for name in "help eye sidebar-collapse sidebar-expand download folder calendar".split():
        assert "<svg" in render('{{ icon("%s") }}' % name)


# --- restyle: sidebar and shell ----------------------------------------------


def test_sidebar_collapse_button_footer_and_filled_active(client):
    html, nav = nav_html(client, "/instellingen/grootboek")
    assert re.search(r'<button[^>]*data-sidebar-collapse[^>]*aria-expanded="true"[^>]*aria-label="Menu inklappen"', html)
    footer = nav[nav.index("nav-footer"):]
    assert "Instellingen" in footer and 'aria-current="page"' in footer
    assert nav.count('aria-current="page"') == 1
    # every nav item keeps an accessible name and a tooltip for the collapsed state
    for item in NAV_ITEMS:
        assert re.search(rf'<a class="nav-link[^"]*" href="{item.path}" title="{item.label}[:"][^>]*>{item.label}</a>', nav)


def test_head_script_restores_collapsed_state_before_paint(client):
    head = client.get("/bank").text.split("</head>")[0]
    assert "bh.sidebar" in head and "sidebar-collapsed" in head and "try" in head


def test_restyle_css_contract():
    css = (STATIC / "app.css").read_text()
    for cls in (
        ".stat-cards .stat-card .stat-card__title .stat-card__cells .stat-cell .stat-cell__label .stat-cell__value "
        ".segmented .segmented--small .drawer .drawer__header .drawer__body .drawer-scrim "
        ".modal__header .modal__body .modal__footer .dropzone .settings-layout .settings-nav .settings-nav__heading "
        ".row--done .row--warn .pager--sticky .help-fab .page-header__icon .page-header__tabs"
    ).split():
        assert re.search(re.escape(cls) + r"[\s,:{\[.>]", css), cls
    assert "html.sidebar-collapsed" in css and "prefers-reduced-motion" in css
    assert "html:not(.js) dialog.modal" in css


def test_js_contract():
    js = (STATIC / "app.js").read_text()
    for needle in ("data-drawer-open", "data-modal-open", "data-modal-close", "data-sidebar-collapse",
                   "bh.sidebar", "showModal", "htmx:afterSwap", "Escape", "data-open-on-load", "try {"):
        assert needle in js, needle
