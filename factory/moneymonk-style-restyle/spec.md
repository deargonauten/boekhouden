Status: APPROVED

# moneymonk-style-restyle: pages closer to the reference accounting-app layout

## Goal and context
User request (Dutch): "ik wil nog wat meer aanpassingen. Kijk naar dit design (en de functies). Ik wil dat je de pagina's meer zo vormgeeft. Als je features ziet die we kunnen gebruiken voor een simpele boekhoudtool, schrijf die dan op. Aan het einde kunnen we dan door de features lopen."

Two deliverables:
1. This spec: a second restyle pass over the EXISTING screens, building on the design system from `factory/ui-redesign/spec.md` (tokens in `app/web/static/app.css`, macros in `app/web/templates/partials/_ui.html`, sidebar in `partials/sidebar.html`, `app/web/navigation.py`, `app/web/static/app.js`). Extend, do not rebuild. No new business features.
2. `factory/moneymonk-style-restyle/feature-candidates.md`: prioritized list of functional features seen in the reference screenshots, for the user to accept/reject at the end. Nothing from that list is built in this run.

Reference screenshots (read, in `<tmp>/images/`): 4 dashboard, 5 bank list, 7 bank list with right drawer, 8 file processing split view, 9 grootboek grouped table, 10 RGS indelen, 11/12 btw-aangifte, 13 settings with secondary nav, 14 boekhoudrobot settings, 15/16 "Transacties toevoegen" modal. Patterns taken from them:
- Sidebar: section headings in bold, icon + label items, filled-blue active item, collapse button top right, footer row with settings gear (active state when in settings).
- Page: white header band with big icon + bold title (28-32px), tab bar directly under the title with an underline on the active tab, full-width band; light-gray body with white bordered cards.
- Cards in pairs with a header and two stat cells ("Te ontvangen" / "Vervallen"); big numbers; bordered stat blocks.
- Lists: filter row (year, select, search), rows with a green left bar when processed, sticky footer with page indicator and "Volgende".
- Right-side drawer with its own tab strip for a selected row; modal with tabs and a dashed drop zone; segmented pill toggles ("Per kwartaal | Per maand | Per jaar", "Factuur | Transactie"); round floating "?" help button; secondary settings navigation column with grouped headings.

Current state (inspected): `app.css` 588 lines with tokens (primary `#3b5bdb`, bg `#f6f7fb`); `_ui.html` macros: `icon, page_header, tabs, toolbar_search, pill, notice, error_box, empty_state, pager, row_menu`; sidebar already has grouped sections, icons, glossary sub-lines (`nav-sub`), pinned Instellingen group, mobile drawer via `data-nav-toggle`; `app.js` (98 lines) handles tooltips, menu, nav drawer, client-side filter; screen CSS in `static/css/{ledger,inbox,relations}.css`; settings pages use `ledger/_settings_nav.html` (`settings_header` macro, page header plus tabs for Grootboek/Dagboeken/Boekjaren).

## Non-goals
- No new functional features: no bank import, no bank list page, no btw-aangifte, no dashboard logic, no charts, no RGS-indelen, no boekhoudrobot, no checkboxes/bulk actions, no notifications bell, no workspace/company switcher, no user chip (single user, no user data exists), no "Nieuwe features" button.
- Do not copy the reference product's logo, name, wording or illustrations. Own name "Boekhouden" and own logo mark stay.
- No dashboard page in this run (decision below). No new routes except `/help` (glossary page, see below).
- No node build, no CSS framework, no CDN, no web fonts, no icon font (inline SVG via `icon()`), no new JS dependencies.
- No data model or migration changes.

## User stories
- As a user I see a clear page: big title with icon, tabs right under it, white cards on a light-gray background, like the apps I know.
- As a user I can open a boeking in a side drawer from the list without losing my place in the list, and still get a normal page without JavaScript.
- As a user I can add a file (inbox) or a rekening (grootboek) from a pop-up (modal) instead of scrolling to a form.
- As a user in Instellingen I see a second navigation column with all settings pages grouped, so I know what exists.
- As a user I get a round "?" button on every page that leads to a plain-Dutch explanation of all bookkeeping terms.
- As a user I can collapse the sidebar to icons to get more room.
- As a user I see processed items marked with a green left bar and a pill, so "wat is al klaar" is obvious at a glance.

## Decisions (explicit)
### New components built now (all in part 1, foundation)
1. **Page header band** (extension of `page_header`): optional icon in front of the title, optional tab bar inside the band. Backwards compatible.
2. **Stat-card pair** (`stat_cards` macro): card with title header and 2 cells (label, big value, optional tone). Used where real data exists (Inbox counts, Boekjaren).
3. **Segmented toggle** (`segmented` macro): pill-shaped link group, `aria-current`; for view switches that keep a URL parameter.
4. **Drawer** (`drawer` macro + JS): reusable right-side panel.
5. **Modal** (`modal` macro + JS, native `<dialog>`): reusable pop-up with progressive-enhancement fallback.
6. **Secondary settings navigation** (`base_settings.html` layout + `SETTINGS_NAV` in `navigation.py`): second column next to the sidebar for the settings pages.
7. **Sidebar upgrades**: collapse button (icon-only mode, state remembered in `localStorage`), footer row with gear (Instellingen) in place of the pinned group look, filled active item.
8. **Floating help button** (`.help-fab`) in `base.html`, linking to a new read-only `/help` page that lists the glossary (existing data in `app/domain/glossary.py`).
9. Row state bars `.row--done` (success) and `.row--warn` (warning): left bar on the first cell.
10. Sticky pager variant `.pager--sticky` (stays at the bottom of the viewport inside the card).

### Not built: dashboard
A dashboard page is NOT built in this run. Reason: it would need new route, new navigation entry, new glossary terms and queries (open debiteuren/crediteuren, btw te betalen, resultaat), which belong to the backlog items "Dashboard" and "Reports", and fake or empty numbers mislead. Stat-card pairs are instead applied on existing pages using existing counts. The dashboard is item 1 in `feature-candidates.md`.

### Palette (extend tokens only)
Shift toward a clear mid-blue while keeping WCAG AA with white button text:
- Light: `--primary: #2d6fb8` (white text 5.1:1), `--primary-hover: #255d9c`, `--primary-soft: #e7f0fa`, `--info-soft: #e7f0fa`, `--focus-ring` alpha of `45 111 184`. `--bg: #f5f6f8` (neutral light gray), `--surface: #ffffff`, `--border: #e1e4ea`, `--border-strong: #c5cbd6`.
- Dark: `--primary: #6fb0ee`, `--primary-hover: #8cc2f4`, `--primary-soft: #1d3248`, `--primary-fg: #0b1020`.
- New tokens: `--nav-active-bg: var(--primary)`, `--nav-active-fg: var(--primary-fg)`, `--band-bg: var(--surface)`, `--bar-success: var(--success)`, `--bar-warning: var(--warning)`, `--text-3xl: 32px`, `--sidebar-width-collapsed: 72px`, `--settings-nav-width: 232px`, `--drawer-width: 30rem`.
- Radius: `--radius: 8px`, `--radius-lg: 12px` (slightly tighter cards). Cards get a 1px `--border` and `--shadow-sm`. Keep all existing token names; only values change. No hard-coded hex outside the token blocks.
- All existing foreground/background pairs must still reach 4.5:1 (check pills, nav-sub on filled active item, tab counts) in light and dark.

### Pages restyled (all existing)
Boeken (list, detail, form), Inbox (list, detail, review, missing), Relaties (list, form), Instellingen (Grootboek, Dagboeken, Boekjaren), placeholders and 404, plus the sidebar/base shell. Placeholders (Bank, Verkoop, Inkoop, BTW, Rapportages, Activa) get the new header band and empty state only.

## Design system additions (contract shared by all parts)

### CSS classes (defined in `app/web/static/app.css` by part 1; parts 2 and 3 only use them)
- Header band: `.page-header` becomes the full-width white band (`--band-bg`, bottom border), containing breadcrumb (small, above), `.page-header__title` with `.page-header__icon` (28px, muted-primary) + `h1` (32px bold), `.page-header__actions`, and `.page-header__tabs` (the tab bar; `.tabs` inside it get the band's bottom border and no extra margin). Body content below sits on `--bg` with `max-width: var(--content-max)`. Templates must NOT need a body wrapper; the band is full-bleed through CSS on `.content` (builder chooses the CSS technique, e.g. `.content { padding: 0 }` and horizontal padding applied to `.content > :not(.page-header)`). Mobile: band padding shrinks, title 24px, tabs scroll horizontally.
- `.stat-cards` (grid, 2 per row, 1 on mobile) containing `.stat-card` (`.stat-card__title` header row with bottom border, `.stat-card__cells` 2 columns with divider, `.stat-cell`, `.stat-cell__label`, `.stat-cell__value` 24px tabular-nums, tone modifiers `--success --warning --danger`).
- `.segmented` (inline-flex, gray track `--surface-2`, radius pill, items as links or buttons, active item white with shadow-sm, `aria-current="page"`), `.segmented--small`.
- `.drawer` (fixed right, full height, width `min(var(--drawer-width), 100vw)`, `--surface`, left border, shadow-md, `transform` slide-in respecting `prefers-reduced-motion`), `.drawer__header`, `.drawer__body` (scrolls), `.drawer__footer`, `.drawer-scrim`. Open state: attribute `data-open` on `.drawer` and on `html` (`data-drawer-open`) to lock body scroll.
- `.modal` on `<dialog>`: centered card, `max-width: 40rem`, `::backdrop` uses `--overlay`, `.modal__header` (title + close `.btn-icon`), `.modal__body`, `.modal__footer`. Fallback: `html:not(.js) dialog.modal` renders as a normal in-page card (`display:block; position:static`).
- `.dropzone` (dashed border, centered text, hover/drag state via `data-dragover`).
- `.settings-layout` (grid: `--settings-nav-width` + content), `.settings-nav` (heading `.settings-nav__heading`, links, `aria-current="page"` shown primary + semibold), below 900px becomes a horizontal scrolling strip above the content.
- `.row--done`, `.row--warn`: `box-shadow: inset 3px 0 0 var(--bar-success|--bar-warning)` on the first `td`.
- `.pager--sticky`: `position: sticky; bottom: 0; background: var(--surface); border-top` inside the card; the count text stays "Toont X-Y van Z ...".
- `.help-fab`: fixed bottom-right 48px round primary button with "?" (inline SVG icon `help`), `aria-label="Uitleg over begrippen"`, visible focus ring, hides in print and when the drawer/modal is open.
- `.sidebar` collapsed state via `html.sidebar-collapsed` (desktop only, >= 900px): width `--sidebar-width-collapsed`, labels and `nav-sub` visually hidden (not `display:none` for the link name: use `.visually-hidden` technique so screen readers still read the label), group labels replaced by a thin divider, tooltip via `title`. Default expanded. Collapse state persists in `localStorage` key `bh.sidebar` (wrapped in try/catch); inline script in `<head>` applies the class before paint.
- Sidebar active item: filled `--nav-active-bg` with `--nav-active-fg`, `nav-sub` on the active item inherits foreground at 85% opacity (contrast verified); the old left accent bar is removed.
- Sidebar footer: the Instellingen item renders as a footer row (gear icon + label "Instellingen", `aria-current` when active) pinned at the bottom with a top border; the plain-Dutch sub-line rule applies to every item that has a `term_key` (Instellingen has none today).

### Jinja macros (`app/web/templates/partials/_ui.html`, part 1)
Existing macros keep their signatures. Additions:
- `page_header(title, breadcrumb=[], action_label=None, action_href=None, term=None, lead=None, icon_name=None, tab_items=None, tab_label=None)`: new optional `icon_name` (rendered with `icon()`), and `tab_items`/`tab_label` render `tabs(...)` inside `.page-header__tabs` in the band.
- `stat_cards(cards)`: `cards` is a list of `{"title": str, "term": key_or_None, "cells": [{"label": str, "value": str, "tone": None|"success"|"warning"|"danger", "href": None|str}, ...]}`; renders `.stat-cards`; `info(term)` next to the title when given. Values are pre-formatted strings (use `|euro` in the caller for money).
- `segmented(items, aria_label)`: items `(label, href, active, term_key_or_None)`; links (`hx-boost="false"` not needed; plain GET), `aria-current="page"` on the active one.
- `drawer(id, title)`: `{% call drawer("boeking-drawer", "Boeking") %}placeholder{% endcall %}`; renders the empty shell (`<aside class="drawer" id=... role="dialog" aria-modal="true" aria-labelledby=... hidden>` with header, close button `aria-label="Sluiten"`, `<div class="drawer__body" id="{{id}}-body">`) plus `<div class="drawer-scrim" hidden>`. The caller body is the fallback/loading text.
- `modal(id, title, open=False)`: `{% call modal("upload", "Bestand toevoegen", open=error) %}body{% endcall %}`; renders `<dialog class="modal" id=... aria-labelledby=...>`; `open=True` sets `data-open-on-load` so JS opens it on load (used when the server re-renders with a form error so the error is visible).
- `dropzone(input_name, accept, label, hint, multiple=True)`: styled label around a native file input (works without JS), text "Klik om bestanden toe te voegen of sleep ze hierheen."
- `icon()` gets extra names: `menu` (exists), `help`, `eye`, `sidebar-collapse`, `sidebar-expand`, `download`, `folder`, `calendar`. Unknown name still raises `ValueError`.

### JS (`app/web/static/app.js`, part 1; stays vanilla, deferred; total under 260 lines)
- Drawer: any element with `data-drawer-open="#id"` opens that drawer on click (links keep their `href` as non-JS fallback, so JS calls `preventDefault` only when the drawer exists). Close: close button, scrim click, Escape. Focus moves into the drawer on open and returns to the trigger on close; Tab is kept inside (simple trap). When the trigger also has `hx-get` + `hx-target="#id-body"` + `hx-push-url="false"` + `hx-boost="false"`, htmx loads the content and JS opens the drawer on `htmx:afterSwap` for that target.
- Modal: `[data-modal-open="#id"]` calls `showModal()`; close on `[data-modal-close]`, Escape (native), backdrop click. `dialog[data-open-on-load]` and `location.hash === "#id"` open on load. Drag-over state on `.dropzone`.
- Sidebar collapse: `[data-sidebar-collapse]` toggles `html.sidebar-collapsed`, updates `aria-expanded` and `aria-label` ("Menu inklappen" / "Menu uitklappen"), persists in `localStorage` (try/catch).
- Existing behaviour (tooltips, menus, nav drawer, filter) unchanged.

### Routes (part 1)
- `GET /help` -> `help.html` ("Uitleg van termen"): page header with icon, a client-side search (`data-filter-table`), cards per theme (or one alphabetical list) rendering every glossary entry as "plain Dutch first, bookkeeping term in parentheses, then explanation". Data comes from the existing glossary; no new data. Not in the sidebar. Linked from the floating `?` button, the 404 page and placeholder pages. Builder verifies `tests/test_plain_language.py`; if the glossary page (which by nature lists bare terms in definition lists) trips the scanner, add it to a documented exclusion for that page only, with a comment, instead of weakening the scanner.
- Route code lives in `app/web/routes.py`; logic (listing glossary) in a small function in `app/domain/glossary.py` if needed (append-only edit, new function `all_terms()` if it does not exist).

### Settings layout (part 1 provides, part 2 consumes)
- `app/web/templates/base_settings.html` extends `base.html`, defines `{% block settings_content %}` inside `.settings-layout` with the `.settings-nav` column rendered from `SETTINGS_NAV` (passed as template global `settings_nav` by `app/web/__init__.py` with the active item marked by `current_path`).
- `navigation.py`: `SETTINGS_NAV: list[SettingsGroup]` with `SettingsGroup(label, items)` and `SettingsItem(label, path, term_key|None)`. Groups: "Boekhouding" (Grootboek `/instellingen/grootboek`, Dagboeken `/instellingen/dagboeken`, Boekjaren `/instellingen/boekjaren`). Labels carry plain Dutch with `info()` for glossary terms (grootboek, dagboek, boekjaar); the section heading is plain ("Boekhouding"). Only existing pages are listed; no disabled "binnenkort" entries.
- `ledger/_settings_nav.html` `settings_header(current)` keeps its name, but now renders only `page_header` (icon "settings", title = current page, breadcrumb Instellingen > current); the tab row is removed because the secondary nav replaces it. Settings templates extend `base_settings.html`.
- `/instellingen` landing behaviour is unchanged by this run (whatever it does today).

## Screen-by-screen
- **Shell (part 1)**: base layout with collapsible sidebar, header band, help button, gray body. Sidebar top: brand + collapse button (no company switcher). Placeholder and 404: band with icon, `empty_state`, link to Inbox and to `/help`.
- **Boeken `/boeken` (part 2)**: header band with icon `book`, title "Boeken", CTA "Nieuwe boeking"; dagboek tabs move into the band (`tab_items`); filter row card: search plus a year/boekjaar select is NOT added (no new filter); rows show plain date, number, omschrijving, bedrag. Storno rows get `row--warn`. Each row has a "Bekijken" link that opens the **drawer** with the boeking detail (see below); the number stays a normal link to the full page. Pager is `pager--sticky`. Stat cards: none (no real data beyond total).
- **Boeking detail (part 2)**: the existing detail content is split into a partial `ledger/_entry_detail_body.html` used in the drawer and in the full page. Drawer shows header (boekstuknummer, datum, status pill), a compact tab strip as `segmented`-style links only if the content has sections (Regels / Documenten is not available; use a single "Regels" section, no empty tabs), the lines table, and the "Storno" action (existing form, same confirmation). Server: the existing detail route returns only the partial when header `HX-Target` equals `boeking-drawer-body`; otherwise the full page (boosted requests have `HX-Target: body`, so compare exactly). Errors stay plain Dutch.
- **Nieuwe boeking form, line row (part 2)**: restyled in white bordered cards; the "Verschil" line becomes a right-aligned totals block ("Totaal debet", "Totaal credit", "Verschil") like the totals block in screenshot 8; no logic change. Sticky `form-actions` footer with primary "Boeking opslaan".
- **Grootboek (part 2)**: `base_settings.html` layout; band with search (`toolbar_search`/client filter) and CTA "Rekening toevoegen" opening a **modal** with the existing add form (form posts as today; on validation error the page re-renders with the modal open via `open=True` and `error_box` inside it). Table per rekeningtype card with columns Code, Naam (plain), Soort, status pill; the existing columns stay (no new columns such as "selecteerbaar bij" or default btw code: those need data that does not exist). Kebab `row_menu` replaces icon buttons only where there are 2+ actions; keep single icon buttons otherwise.
- **Dagboeken, Boekjaren (part 2)**: same layout. Boekjaren: top `stat_cards` pair: card "Boekjaar" (cells: Open perioden, Vergrendelde perioden) using counts computed from data the route already loads (count in the template via `selectattr`; no new queries); periods table with `row--done` for vergrendeld periods; "Boekjaar afsluiten" stays a danger button with confirm.
- **Relaties (part 3)**: band with icon `users`, tabs Alle / Klanten / Leveranciers in the band; toolbar card with search and a `segmented` toggle "Actieve relaties | Ook gearchiveerd" (replaces the switch; maps to existing `gearchiveerd=1`, no new parameter); table unchanged in content; pager sticky. Form: cards as today in the new look.
- **Inbox list (part 3)**: band with icon `inbox`, title "Inbox", CTA "Bestand toevoegen" opening the upload **modal** (`data-modal-open="#upload"`, href `#upload` fallback; non-JS shows the modal content as an in-page card). Modal body uses `dropzone` (accept PDF/images as today, same form action and field name; extraction/upload behaviour unchanged) plus plain-Dutch help text. Status tabs (Alle/Nieuw/Herkend/Geboekt with counts and `info()`) move into the band. Above the table: `stat_cards` with two pair cards using existing counts: "Te verwerken" (Nieuw, Herkend) and "Klaar" (Geboekt, Totaal). Rows with status geboekt get `row--done`. Row click/"Bekijken" opens the inbox detail (file preview + facts) in the **drawer** via the same HX-Target mechanism (partial `inbox/_detail_body.html`); "Nakijken" stays a link to the full review page. Pager sticky.
- **Inbox detail, missing, review (part 3)**: band with icon; review keeps its two-column layout and sticky bottom action bar; restyle only (cards, totals block as in screenshot 8: "Totaal exclusief btw / btw / Totaal"; use the existing fields only). Flags stay pills.
- **Help page (part 1)**: see Routes.

## Acceptance criteria
1. Tokens: values changed as listed in "Palette"; all existing token names still exist; new tokens added; no hard-coded hex outside the `:root` / dark token blocks in `app.css`; screen CSS files use tokens only. AA contrast holds for text on primary, primary-soft, success/warning/danger soft backgrounds in light and dark (verify with a small script or documented calculation in the part report).
2. Every page shows the header band (full-bleed white, bottom border) with icon and 28-32px title; list pages with tabs show them inside the band. Placeholder and 404 included. Macro `page_header` remains backwards compatible (existing callers render unchanged without `icon_name`/`tab_items`).
3. Sidebar: filled active item with `aria-current="page"`; collapse button toggles icon-only mode, persists across reloads (`localStorage`), works without errors if storage is blocked; collapsed links still have accessible names (visible text hidden visually, `title` set); footer row with gear for Instellingen; every item that has a glossary sub-line still renders it when expanded; mobile (< 900px) still uses the off-canvas drawer and ignores the collapsed state.
4. Components exist with the signatures above and are tested: `stat_cards`, `segmented`, `drawer`, `modal`, `dropzone`, extended `page_header`. `icon()` knows the new names.
5. Drawer: opens from `data-drawer-open` triggers, closes on X, scrim click and Escape, focus moves in and returns, `role="dialog"` + `aria-modal="true"` + `aria-labelledby`; page behind does not scroll while open. Without JS the trigger link navigates to the full page.
6. Boeken: "Bekijken" opens the drawer with the boeking detail loaded via htmx; a request with `HX-Target: boeking-drawer-body` returns only the partial (no `<html>`, no sidebar); a normal and a boosted (`HX-Target: body`) request return the full page. Unknown id still gives the existing plain-Dutch 404. The detail content in drawer and page is identical (same partial).
7. Modal: Inbox "Bestand toevoegen" and Grootboek "Rekening toevoegen" open a modal with focus inside, close on X/Escape/backdrop; a validation error re-renders the page with the modal open and the plain-Dutch error visible inside it; without JS the form is visible in the page (no hidden/unreachable form); existing POST routes, field names and success/error messages are unchanged.
8. Inbox shows two stat-card pairs with counts equal to the counts in the status tabs; geboekt rows have `row--done`; Boekjaren shows the open/vergrendeld counts card; vergrendelde periods have `row--done`; storno rows in Boeken have `row--warn`. Colour is never the only carrier (status pill text remains).
9. Relaties: `segmented` toggle "Actieve relaties | Ook gearchiveerd" sets/clears `gearchiveerd=1`; tabs Alle/Klanten/Leveranciers keep `soort`; all params are preserved in links and pager.
10. Settings pages (Grootboek, Dagboeken, Boekjaren) render in `.settings-layout` with the secondary nav (group heading "Boekhouding", three links, active one `aria-current="page"`); the former tab row is gone; at < 900px the nav is a horizontal strip above the content, no horizontal page scroll.
11. `/help` returns 200 and lists every glossary entry (count in page equals number of glossary keys, so a missing entry is caught); the floating `?` button (`aria-label="Uitleg over begrippen"`, `href="/help"`) is present on every page extending `base.html`, including 404 and placeholders; it is not rendered inside the drawer/modal and does not overlap the sticky pager (offset above it).
12. Sticky pager: `pager--sticky` inside the list card on boeken, relaties, inbox; the count text and numbered links are unchanged (existing pager tests keep passing).
13. Responsive: at 375px, 768px and 1280px no horizontal page scroll; drawer is full width on mobile; modal fits with internal scroll; stat cards stack to one column; tab bars scroll horizontally inside the band.
14. Accessibility: visible `:focus-visible` rings on all new controls; icon-only buttons have `aria-label`; `prefers-reduced-motion` disables slide/fade; dialog/drawer have accessible names.
15. No external requests: no CDN, no remote fonts or images (`grep -R "https\?://" app/web/templates app/web/static/app.css` shows no loading references).
16. All existing tests pass (`uv run pytest`), including `tests/test_plain_language.py`, `tests/test_info_component.py`, `tests/test_web.py`, `tests/test_ui_components.py`. Tests asserting changed markup (e.g. settings tabs, sidebar pinned group, `.accent` bar) are updated by the part that changes the markup, keeping the behaviour they test.
17. Plain-language (CLAUDE.md): new visible Dutch text is plain; no new bookkeeping term is introduced. New UI words and their handling: "Uitleg van termen" and "Bestand toevoegen"/"Rekening toevoegen" (plain Dutch, no glossary), "Boekhouding" as settings group heading (plain), "Te verwerken", "Klaar" (plain). The existing terms shown on the new screens (grootboek, dagboek, boekjaar, periode, vergrendelen, storno, debet/credit, relaties) keep their `info()` marker next to them, including in the new settings nav links, drawer header and modal titles; no term appears bare as label/heading/th. Every glossary key is still rendered somewhere (nav sub-lines, `/help`). Suggested defaults unchanged (the add-rekening form keeps its existing defaults); errors keep existing plain-Dutch strings, e.g. "Debet en credit zijn niet gelijk: er ontbreekt €12,10", rendered with `error_box` also inside drawer/modal.
18. The upload dropzone helper text states what is accepted and what happens next in plain Dutch ("Je bestand wordt bewaard en daarna uitgelezen."); the help page opens from every screen in one click.

## Technical approach
- Files: `app.css` (tokens, components; part 1), `app.js` (part 1), `css/ledger.css` (part 2), `css/inbox.css` and `css/relations.css` (part 3). Screen CSS adds only screen-specific layout.
- Drawer/modal content is server-rendered Jinja partials; htmx fetches the partial. No JSON endpoints. Routes decide partial vs. full page via `request.headers.get("HX-Target") == "<drawer>-body"` (a tiny helper `is_drawer_request(request, "boeking-drawer")` in `app/web/__init__.py`, part 1; routes only call it, no logic in handlers).
- Stat-card values for Inbox come from the status counts the inbox route already computes for the tab counts; for Boekjaren from the loaded period lists. If a count is not currently available in the route context, the owning part adds it to the template context via an existing domain function (no new SQL beyond a count over what is already queried).
- Collapsed sidebar and help button are CSS/JS only; the `/help` page is the only new route.
- Dark mode: only token values change; verify drawer, modal, dropzone, stat cards in dark.
- Money in stat cards uses the existing `|euro` filter if any money is shown (none planned).

## Work breakdown
Dependency order: **Part 1 first** (tokens, components, base, sidebar, macros, `/help`). Parts 2 and 3 are disjoint and run in parallel after part 1 lands (or concurrently coding to the contract above, integrated after part 1 merges).

**Part 1: foundation** (owns): `app/web/static/app.css`, `app/web/static/app.js`, `app/web/templates/base.html`, `app/web/templates/base_settings.html` (new), `app/web/templates/help.html` (new), `app/web/templates/placeholder.html`, `app/web/templates/404.html`, `app/web/templates/partials/*`, `app/web/navigation.py`, `app/web/__init__.py` (globals, `is_drawer_request`), `app/web/routes.py` (`/help`), `app/domain/glossary.py` (append only: `all_terms()` if needed), `tests/test_ui_components.py`, `tests/test_web.py`, `tests/test_info_component.py`, new `tests/test_help_page.py`. Deliver: palette, band, sidebar (collapse, footer, active), all new classes and macros, JS, settings layout and `SETTINGS_NAV`, help page and button, styleguide block updated at the top of `_ui.html`.

**Part 2: ledger screens** (owns): `app/web/templates/ledger/*` (incl. `_settings_nav.html`, new `_entry_detail_body.html`), `app/web/ledger_routes.py`, `app/web/static/css/ledger.css`, `tests/test_ledger_web.py`, `tests/ledger/*` additions. Covers boeken list/detail/form/line row, drawer for boeking detail, grootboek (modal), dagboeken, boekjaren (stat card, row--done), settings layout adoption.

**Part 3: relations and inbox** (owns): `app/web/templates/relations/*`, `app/web/templates/inbox/*` (incl. new `_detail_body.html`), `app/web/relations_routes.py`, `app/web/inbox_routes.py`, `app/web/extraction_routes.py`, `app/web/static/css/relations.css`, `app/web/static/css/inbox.css`, `tests/test_relations_web.py`, `tests/test_inbox_web.py`, `tests/test_extraction_web.py`, `tests/relations/*`. Covers relaties list/form (segmented), inbox list (modal, stat cards, drawer, row--done), detail, missing, review.

Shared, edited by the integrator after merge: `tests/test_plain_language.py` (`PAGES` list incl. any new URLs reported by parts 2 and 3, `/help` handling).

Integration points: macro names/signatures above, CSS class names, `HX-Target` ids (`boeking-drawer-body`, `inbox-drawer-body`), modal ids (`upload`, `rekening-toevoegen`), `SETTINGS_NAV`, `base_settings.html` block name `settings_content`.

## Test strategy
- Part 1 (`tests/test_ui_components.py`): render `stat_cards` (two cells per card, tone class, term info), `segmented` (single `aria-current`), `drawer` (role, aria attributes, body id, empty shell), `modal` (dialog element, `data-open-on-load` only when `open=True`), `dropzone` (native `input type=file`, `multiple` toggle), extended `page_header` (icon and tabs inside band; old call without new params unchanged), new `icon` names, unknown name raises. Sidebar: collapse button present with `aria-expanded`, footer gear row, active item marked, all glossary sub-lines present, no external URLs. `/help`: 200, number of entries equals glossary size, floating button on a normal page, on 404 and on a placeholder, `is_drawer_request` unit test (drawer id matches, `body` target and missing header do not).
- Part 2: detail route returns partial for `HX-Target: boeking-drawer-body` (no `<html>`), full page otherwise (also for `HX-Target: body`), 404 plain Dutch; settings pages contain `.settings-nav` with the active link; Boekjaren counts card correct; storno row has `row--warn`; add-rekening error re-renders with `data-open-on-load` and the plain-Dutch message; existing pagination/`q` tests stay green.
- Part 3: inbox stat-card counts equal tab counts; geboekt rows have `row--done`; upload form still posts and the fallback form exists inside the dialog markup; detail partial for `HX-Target: inbox-drawer-body`; relaties segmented toggle keeps `soort`, `q`, `page`; existing extraction/review tests unchanged.
- Glossary: extend `PAGES` for changed screens; keep "no unused glossary key" green.
- Manual/visual reviewers: run `./boekhouden`, check every screen at 375/768/1280px in light and dark, keyboard-only drawer and modal, collapse and reload, without JS (disable) for modal fallback and drawer link fallback.

## Risks and decisions made
- Brand blue: `#4a90d9` fails AA with white text (about 3.3:1). Decision: `#2d6fb8` for primary (close hue, 5.1:1); the lighter blue is used only as `--primary-soft`/tints. Easy to change through tokens.
- Full-bleed header band inside a padded `.content`: decided as a CSS-only change so existing templates need no wrapper; reviewers grep that no template adds layout wrappers for it.
- Drawer plus `hx-boost="true"` on body: boosted requests also carry `HX-Request`; therefore the partial is chosen only by an exact `HX-Target` id match, and drawer triggers set `hx-boost="false"` explicitly.
- Modal without JS: fallback renders the form in-page; when JS is on the same markup is a dialog. Risk of forms inside `<dialog>` being submitted via htmx boost: forms keep their current boost behaviour (409/422 swap script remains), dialog is reopened on re-render through `data-open-on-load`.
- Plain-language tests scan HTML; new wrappers (drawer header, modal title, settings nav, `/help`) can show terms bare. Mitigation: `info()` next to every term; run `tests/test_plain_language.py` after each template change; `/help` is the only page allowed a documented exclusion.
- Collapsed sidebar hides the plain-Dutch sub-lines (CLAUDE.md wants them visible). Decision: collapsed is an opt-in user preference, default expanded, labels stay available through `title` and accessible names; the full sub-lines return as soon as the user expands.
- Dashboard deferred (see Decisions); settings nav lists only existing pages to avoid dead links; company switcher, user chip, notification bell are intentionally absent because the app is single-user and has no such data.
- Without `HX-Target` tests existing code may render drawers' content paths twice (page and partial): shared partial prevents drift.
- Parallel parts could drift from the contract: part 1 merges first; reviewers grep templates for unknown class names.
