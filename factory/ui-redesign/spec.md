Status: APPROVED

# ui-redesign: modern, consistent UI and better UX

## Goal and context
User request: "Ik wil dat het mooier is, en beter ge-UX'ed."
Restyle the whole existing Jinja2 + HTMX UI into one polished design system, and improve UX patterns (page header, toolbars, status pills, row actions, pagination, empty states, feedback). Same features and Dutch wording; the look and structure change.

References:
- Dribbble shot 21340010: WebFetch returned an empty page (blocked). Not used. Design follows the two screenshots.
- Screenshot 2 (Vantus ERP): light sidebar with grouped sections and an active-item highlight; page header with breadcrumb and primary CTA on the right; one white card holding toolbar (search, sort, filter, export) and table; checkbox column, row kebab menu; "Pagina 2 van 10" with Vorige/Volgende; toggle switches.
- Screenshot 3 (Fluent Affiliate): status tabs with underline (Alle/Actief/...); search plus filter toolbar; coloured status pills with a dot; row action icons; "Toont 14 van 140 resultaten" with numbered pagination; large rounded primary button; generous whitespace.

Current state (inspected): one `app/web/static/app.css` (272 lines, dark sidebar, partly tokens, tables without cards), `base.html` with CSS-only mobile menu, `partials/sidebar.html`, `partials/_info.html` (info macro and term_label), templates under `ledger/`, `relations/`, `inbox/`. `/boeken` has server pagination (50 per page, `dagboek` filter). `/relaties` has server `q`, `soort`, `gearchiveerd`. `/inbox` has a status filter shown as a plain list. htmx is vendored. `tests/web_helpers.py` and `tests/test_plain_language.py` enforce glossary coverage by scanning HTML (they strip td/dd/option/nav/aside/tooltip text).

## Non-goals
- No new features, routes or data model (except search/pagination parameters listed below).
- No node build, no CSS framework, no CDN, no web fonts (system font stack). No icon font; inline SVG only.
- No dark-mode redesign beyond keeping `prefers-color-scheme: dark` working through tokens.
- No dashboard/home page, no charts, no bulk actions, no column chooser, no export.
- Placeholder pages (Bank, Verkoop, ...) only get the new layout and a nicer empty state.

## Brand and visual direction (decided)
Calm indigo-blue primary (`--primary: #3b5bdb`, hover `#324ec0`, soft tint `#eef2ff`). Neutral cool-gray surfaces, white cards on `#f6f7fb` background, 12px card radius, 8px control radius, subtle 1px borders and a very light shadow. Product name stays "Boekhouden" with a small inline SVG logo mark. Light sidebar (white, border-right) as in screenshot 2. Font: `system-ui` stack, base 15px/1.5, headings semi-bold, `font-variant-numeric: tabular-nums` for money. Generous whitespace (card padding 20-24px, row height ~48px).

## User stories
- As the bookkeeper-without-knowledge, I see a clear sidebar with grouped sections and know where I am (active item, breadcrumb).
- As a user, every list page has the same layout: title and one primary button on top, a card with tabs/search/filter, a clean table, result count and pagination.
- As a user, I see status at a glance via coloured pills (Open/Vergrendeld, Nieuw/Herkend/Geboekt, Actief/Gearchiveerd).
- As a user, I get clear feedback after actions (success notice) and readable errors that say what to do.
- As a user on a laptop or phone, the layout stays usable; keyboard focus is always visible.

## Design system contract (shared by all parts)

### Tokens (CSS custom properties on `:root`, in `static/app.css`; dark variants under `@media (prefers-color-scheme: dark)`)
Colors: `--bg --surface --surface-2 --border --border-strong --fg --muted --primary --primary-hover --primary-soft --primary-fg --success --success-soft --warning --warning-soft --danger --danger-soft --info-soft`. Foreground colors on their soft backgrounds must reach WCAG AA (4.5:1) in light and dark.
Type: `--font --text-xs(12px) --text-sm(13px) --text(15px) --text-lg(17px) --text-xl(22px) --text-2xl(28px)`.
Space: `--space-1..8` (4,8,12,16,20,24,32,48px). Radius: `--radius-sm 6px --radius 10px --radius-lg 14px --radius-pill 999px`. Shadow: `--shadow-sm --shadow-md`. Layout: `--sidebar-width 248px --content-max 76rem`. Focus: `--focus-ring: 0 0 0 3px` of primary at 35% alpha; every interactive element gets a visible `:focus-visible` ring. Respect `prefers-reduced-motion`.

### CSS class contract (defined by part 1; parts 2 and 3 only use these, plus their own screen files)
- Layout: `.app-shell`, `.sidebar`, `.content`, `.page-header` (`.page-header__title`, `.page-header__actions`), `.breadcrumb`, `.stack` (vertical gap), `.cluster` (horizontal gap, wraps), `.grid-2`.
- Card: `.card`, `.card__header`, `.card__body`, `.card__footer`, `.card--flush` (no padding, for tables).
- Buttons: `.btn` (primary), `.btn-secondary`, `.btn-ghost`, `.btn-danger`, `.btn-small`, `.btn-icon` (square, needs `aria-label`). Existing classes `btn`, `btn-secondary`, `btn-danger`, `btn-small` keep working, so templates that are not yet migrated still render fine.
- Forms: `.field` (label + control + `.field__hint` + `.field__error`), `.fields` / `.inline-form` (kept, restyled), `.input`, `.select`, `.textarea` (bare `input/select/textarea` inside `.content` are styled by default), `.check`, `.switch` (toggle styled checkbox), `.form-actions` (sticky-ish button row), `.fieldset` card-like grouping. Required marker via `.required`.
- Tables: `table.data` inside `.table-wrap` inside `.card--flush`; `th.num/td.num` right aligned; `.row-actions` (right aligned, holds `.btn-icon` and the kebab); `tr.inactive` muted; sticky header optional; `.table-empty`.
- Pills: `.pill` plus modifier `.pill--neutral | --info | --success | --warning | --danger`, each with a leading dot (CSS `::before`). Legacy `.badge`, `.badge-nieuw/-herkend/-geboekt/-muted` and `.flag-*` stay as aliases mapped to the pill look so unmigrated templates do not break.
- Tabs: `.tabs` (`<nav>`, links with `aria-current="page"` get underline and primary color), `.tab__count` (small count chip). Replaces `.status-filter` and `.subnav` (aliases kept).
- Toolbar: `.toolbar` (flex, wraps; `.toolbar__search` with magnifier icon, `.toolbar__filters`, `.toolbar__spacer`).
- Pager: `.pager` (result count left, page links right).
- Feedback: `.notice` (`--success`, `--info`, `--warning`), `.alert` (error, `role="alert"`); `.empty` (empty state: icon, title, text, CTA).
- Info tooltip: `.info`, `.info-btn`, `.info-tip` keep their markup (tests depend on `data-term`, `role="tooltip"`, `aria-describedby`). Restyle only: round 18px button with SVG-free "i", tooltip as a small dark card with arrow, positioned with `position: absolute` relative to `.info` (fix the current `left: 0` against `.content` so it appears next to the icon), opens on hover and focus, closes on Escape (small JS in `app.js`), never clipped by `.table-wrap` overflow (render tooltip with `position: fixed` via JS placement, or keep inside table-less contexts; builder chooses, must work in `th`).
- Utilities: `.muted`, `.visually-hidden`, `.nowrap`, `.mono`.

### Jinja macro contract: `app/web/templates/partials/_ui.html` (new, part 1)
Import with `{% from "partials/_ui.html" import page_header, tabs, toolbar_search, pill, pager, empty_state, notice, icon, row_menu with context %}`.
- `page_header(title, breadcrumb=[], action_label=None, action_href=None, term=None, lead=None)`: `<header class="page-header">`; breadcrumb is a list of `(label, href_or_None)` and always starts with the section (e.g. `[("Boeken", "/boeken"), ("Nieuwe boeking", None)]`); `<h1>`; optional `info(term)` next to the title; optional lead paragraph; primary CTA as `<a class="btn">` with plus icon. `{% call page_header(...) %}extra actions{% endcall %}` slot allowed via `caller()`.
- `tabs(items, aria_label)`: items are `(label, href, active, count_or_None, term_key_or_None)`; renders `<nav class="tabs">` with `aria-current="page"` on the active one and an `info()` when `term_key` is given.
- `toolbar_search(action, q, placeholder, hidden={})`: GET form, `type="search"`, `name="q"`, magnifier icon, preserves `hidden` params; `hx-boost="false"`.
- `pill(label, tone, title=None)`: tone in neutral/info/success/warning/danger.
- `pager(page, per_page, total, base_url, params={}, noun="resultaten")`: renders "Toont 1-50 van 140 resultaten" and Vorige / numbered (with ellipsis) / Volgende; links built from `base_url` + `params` + `page`; hidden entirely only when `total == 0`; the count line shows when there is a single page; `aria-label="Paginering"`, current page `aria-current="page"`.
- `empty_state(title, text, action_label=None, action_href=None, icon_name="inbox")`.
- `notice(text, tone="info")` (`role="status"`), `error_box(text_or_list)` (`role="alert"`).
- `icon(name, size=18)`: inline SVG, `aria-hidden="true"`, `currentColor`. Names (stroke style, 24px viewbox): plus, search, filter, edit, archive, restore, lock, check, x, chevron-down, chevron-left, chevron-right, more, inbox, book, bank, receipt, users, percent, chart, box, settings, file, upload, alert, info.
- `row_menu(label)` is optional: a `<details class="menu">` kebab (no JS) with items as links or small POST forms; menu closes on outside click via `app.js`. Row actions that exist today (Bewerken, Archiveren/Herstellen, Activeren/Deactiveren, Vergrendelen) become icon buttons with `aria-label` and `title` containing the full plain-Dutch text, e.g. "Relatie archiveren"; destructive/locking actions keep their existing `hx-confirm`.
- Existing `partials/_info.html` (`info`, `term_label`) stays source-compatible; part 1 may restyle its markup but must keep attributes tests depend on.

### Base layout (part 1)
`base.html` provides blocks `title`, `head` (extra CSS per screen), `content`, and optional `breadcrumb`-free layout (breadcrumb is rendered by `page_header`). Structure: `.app-shell` = sidebar + `main.content` inside a max-width container. Skip link "Naar de inhoud" first in the body. Flash/notice region stays inside templates (no new session flash mechanism). Keep `hx-boost="true"` on body and the 409/422 swap script. htmx busy state: a thin top progress bar (`.htmx-request` on body) and existing `.htmx-indicator`.

Sidebar: light, logo mark + "Boekhouden" at top, grouped sections with small uppercase labels from the nav group: group 0 "Verwerken" (Inbox, Boeken, Bank), group 1 "Verkoop en inkoop" (Verkoop, Inkoop, Relaties), group 2 "Aangifte en overzicht" (BTW, Rapportages, Activa), group 3 pinned bottom (Instellingen). Each item: icon + label; the plain-Dutch sub-line from the glossary (`nav-sub`) stays visible under the label (CLAUDE.md requirement) but styled small and muted; active item has primary-soft background, primary text and a left accent bar. `navigation.py` gets `GROUP_LABELS` and an `icon` field per `NavItem` (part 1 owns it); `mark_active` keeps its signature plus the new field. Mobile (< 900px): sidebar becomes an off-canvas drawer toggled by a top bar with menu button (keep the CSS-only checkbox approach or use `<button>` + small JS with `aria-expanded`; closing on link click/Escape). Content padding shrinks, tables scroll in `.table-wrap`, toolbar stacks.

Small JS: `static/app.js` (vanilla, deferred, under 150 lines, no dependencies): tooltip placement and Escape close, menu outside click, drawer toggle, client-side row filter (`<input data-filter-table="#id">` hides non-matching `tbody tr` by text; progressive enhancement, page works without JS). Loaded in `base.html`.

## Page conventions (apply to every screen)
1. `page_header` with breadcrumb; one primary action top right.
2. Content in `.card` / `.card--flush`; lists: tabs or toolbar on top inside the card header, table, `pager` footer.
3. Statuses use `pill`. Money right aligned with `|euro`. Dates `dd-mm-jjjj` (unchanged).
4. Empty states use `empty_state` with plain-Dutch explanation and a CTA; "geen resultaten door filter" shows a short text and a "Wis filters" link.
5. Forms: one column of `.field`s grouped in cards, labels above controls, hint text under the control, errors via `error_box` at the top and field-level where the route already knows the field, primary button bottom left in `.form-actions`, secondary "Annuleren" link next to it.
6. Plain-language rules unchanged: plain Dutch first with the bookkeeping term in parentheses and an `info()` marker; no bare term as label/th/heading. Tooltips and `title` texts come from `app/domain/glossary.py`.

## Screen-by-screen
- Boeken `/boeken` (part 2): header "Boeken" + CTA "Nieuwe boeking"; card with tabs per dagboek (Alle + one tab per active dagboek with `info("dagboek")` on the group label) OR a dagboek select (builder picks tabs when <= 6 journals, else select), search `q` (boekstuk number, omschrijving, referentie), table with pills for "Storno van ..." (warning) and "Gestorneerd" (neutral), pager with result count.
- Boeking detail, nieuwe boeking form, line row partial (part 2): form in cards (Algemeen / Regels); live "Verschil" balance line is only restyled (no logic change); the balance error text stays plain Dutch ("Debet en credit zijn niet gelijk: er ontbreekt €12,10").
- Instellingen (part 2): `_settings_nav.html` becomes `tabs` (Grootboek, Dagboeken, Boekjaren) under a page header "Instellingen" with breadcrumb. Grootboek: add-form in a collapsible card ("Rekening toevoegen" `<details>`), then one card per rekeningtype with table, search (client-side filter) and `switch`-style active toggle or pill plus icon button; system accounts show pill "Systeem". Dagboeken: same pattern. Boekjaren: per year a card with status pill (Open/Afgesloten), periods table with pills (Open/Vergrendeld), lock icon buttons with confirm, "Boekjaar afsluiten" as danger button in the card header.
- Relaties (part 3): header + CTA "Relatie toevoegen"; tabs Alle / Klanten / Leveranciers (replaces the `soort` select; the URL parameter `soort` stays), search, checkbox "Toon ook gearchiveerde relaties" as switch in the toolbar (`gearchiveerd=1` unchanged), table with initial avatar circle + name, soort pill(s), pill Actief/Gearchiveerd, icon actions (Bewerken, Archiveren/Herstellen), pager if more than 50 (new `page` param, 50 per page, see approach). Form: grouped cards (Algemeen, Bedrijfsgegevens met KvK/BTW/IBAN, Adres), existing KvK lookup behavior unchanged.
- Inbox list (part 3): header + CTA "Bestand toevoegen" (jumps to upload card `#upload`); upload as a dashed drop-zone card (native file input styled, text "Sleep bestanden hierheen of kies een bestand", no new JS needed beyond the native input); extraction banner as `notice`; tabs Alle / Nieuw / Herkend / Geboekt with counts and `info()` per status (URL `?status=` unchanged); table with status pills; row action as button ("Lees uit") or link ("Nakijken"); results list as `notice`/`alert` items; empty states.
- Inbox detail, missing (part 3): header + breadcrumb (Inbox > bestandsnaam), facts as definition list in a card, file preview in a card.
- Review `/inbox/{id}/nakijken` (part 3): two-column layout kept (sticky document left, form right), form in cards (Leverancier, Factuur, Regels, Totalen), flags as pills (`flag-medium` -> warning, `flag-low` -> danger, `flag-info` -> neutral), summary line "N velden om te controleren" as a `notice--warning`, sticky bottom action bar with "Klaar met nakijken". No behavior change in the form fields or routes.
- Placeholder and 404 (part 1): `empty_state` ("Deze pagina is nog in ontwikkeling" with a link to Inbox); 404 with link terug naar Inbox.

## Acceptance criteria
1. `app.css` defines all tokens above; no hard-coded hex colors outside the `:root` / dark-mode token blocks in `app.css` (screen CSS files use tokens only). Light and dark both render readable.
2. Every page extends `base.html` and shows the new sidebar (grouped, icons, active state with `aria-current="page"`, glossary sub-lines) and a `page_header` with breadcrumb (placeholder and 404 included).
3. Macros in `partials/_ui.html` exist with the signatures above and are covered by tests (see Test strategy).
4. Every list page (boeken, grootboek, dagboeken, relaties, inbox, boekjaren periods) uses card + table + status pills; lists that can exceed one page show result count and pager (`pager` macro): boeken, relaties, inbox.
5. `/boeken` supports `?q=` (matches entry number, omschrijving, referentie, case-insensitive) combined with `dagboek` and `page`; pager links keep all active params. Invalid/negative page falls back to 1; page beyond the last shows the last page.
6. `/relaties` supports `page` (50 per page) combined with existing `q`, `soort`, `gearchiveerd`; result count text "Toont X-Y van Z relaties".
7. `/inbox` keeps `status` filter and shows counts in tabs; list capped behavior (cap notice) stays, and the cap notice becomes a `notice` with plain Dutch text.
8. All forms use `.field` layout; error messages remain the existing plain-Dutch strings rendered in `error_box` (`role="alert"`); success messages in `notice` (`role="status"`).
9. Empty states exist and are plain Dutch on: boeken (no entries / no match), grootboek search no match, relaties (both cases), inbox (both cases), boekjaren (no year), placeholders.
10. Keyboard: every interactive element has a visible focus ring; skip link works; icon-only buttons have `aria-label`; tooltips open on focus and close on Escape; tab order follows visual order. Colour is never the only status carrier (pills contain text).
11. Responsive: at 375px, 768px and 1280px there is no horizontal page scroll (tables scroll within `.table-wrap`), sidebar is a drawer below 900px, toolbar stacks, review grid becomes one column below 900px.
12. No external network requests: no CDN, no remote fonts or images; `grep -R "https\?://" app/web/templates app/web/static/app.css` shows only form actions-free, non-loading links (e.g. text links in tooltips are fine, no `src`/`href` stylesheet/script).
13. All existing tests pass (`uv run pytest`), including `tests/test_plain_language.py`, `tests/test_info_component.py`, `tests/test_web.py`. Tests that assert specific old markup (e.g. `status-filter`, `subnav`, `badge`) are updated in the same part that changes the markup, keeping the behavior they test.
14. Plain-language: no new bookkeeping terms are introduced by this feature. The UI adds plain-Dutch wording only ("Toont 1-50 van 140 resultaten", "Wis filters", "Sleep bestanden hierheen", "Naar de inhoud"). New glossary entries are only needed if a part adds a term; any new entry goes in `app/domain/glossary.py` and is used with `info()`. A test asserts glossary coverage still holds for every redesigned page (extend PAGES in `tests/test_plain_language.py`; no key may become unused in `UNUSED_OK` terms, i.e. every glossary key is still rendered somewhere, including nav sub-lines).
15. Icon-only row actions keep the full plain-Dutch explanation in `title` (e.g. "Verbergt de relatie in lijsten; bestaande boekingen en facturen blijven bewaard.") and the visible text exists in `aria-label`.

## Technical approach
- Files: `app/web/static/app.css` (tokens, base, components; part 1 only), `app/web/static/app.js` (part 1), per-screen CSS files `app/web/static/css/ledger.css` (part 2) and `css/inbox.css`, `css/relations.css` (part 3), loaded through `{% block head %}` in their templates. A screen file may only add screen-specific layout (review grid, balance line, drop-zone); shared looks belong in `app.css`.
- Domain: add `q: str | None = None` to `ledger.list_entries` (part 2) with SQL `LIKE` on entry_number/description/reference (escape `%` and `_`); relations list function gets `page`/`per_page` and returns total (part 3), following the existing result shape (`items`, `total`, `page`, `per_page`). No logic in route handlers beyond passing parameters and clamping `page >= 1`.
- Icons are inline SVG inside the `icon()` macro, a single switch on name; no sprite file.
- htmx: keep `hx-boost` body default; filters/search are plain GET forms with `hx-boost="false"` as today (full reload is fine, state in URL). No partial-swap rewrites in this feature.
- Errors: unchanged routes and messages; only presentation changes.

## Work breakdown
Dependency order: **Part 1 (foundation) must be merged first.** Parts 2 and 3 depend on it for `app.css`, `partials/_ui.html`, `base.html` (`head` block) and `app.js`. If run in parallel against the contract above, parts 2 and 3 must code strictly to the class/macro names and signatures listed here, and are integrated and tested only after part 1 lands. Parts 2 and 3 are fully disjoint from each other and can run concurrently.

**Part 1: foundation** (owns): `app/web/static/app.css`, `app/web/static/app.js`, `app/web/templates/base.html`, `app/web/templates/partials/*` (sidebar, `_info.html`, new `_ui.html`), `app/web/templates/placeholder.html`, `app/web/templates/404.html`, `app/web/navigation.py`, `app/web/__init__.py` (template globals/filters only), `tests/test_ui_components.py` (new), `tests/test_web.py` and `tests/test_info_component.py` updates. Deliver: tokens, all contract classes, macros, sidebar, mobile drawer, tooltip restyle, JS, and a short "styleguide" comment block at top of `_ui.html` listing macros. Also keep legacy aliases (`.badge*`, `.flag-*`, `.status-filter`, `.subnav`, `.page-head`, `.table-wrap`, `.btn*`) so old templates still render acceptably until parts 2 and 3 migrate.

**Part 2: ledger screens** (owns): `app/web/templates/ledger/*`, `app/web/ledger_routes.py`, `app/domain/ledger/` (only the `q` parameter on `list_entries`), `app/web/static/css/ledger.css`, `tests/test_ledger_web.py` and `tests/ledger/*` additions. Covers boeken list/detail/form/line row, grootboek, dagboeken, boekjaren, settings tabs.

**Part 3: relations + inbox/review** (owns): `app/web/templates/relations/*`, `app/web/templates/inbox/*`, `app/web/relations_routes.py`, `app/web/inbox_routes.py`, `app/web/extraction_routes.py`, `app/domain/relations/` (pagination only), `app/web/static/css/relations.css`, `app/web/static/css/inbox.css`, `tests/test_relations_web.py`, `tests/test_inbox_web.py`, `tests/test_extraction_web.py`, `tests/relations/*`.

Shared, edited by the integrator after merge (not by parts 2/3 in parallel): `tests/test_plain_language.py` PAGES list. Each of parts 2/3 provides its new/changed URLs in its report; the integrator adds them. `app/domain/glossary.py`: only edited if a part adds a term; if so that part reports the key and edits only appended entries to avoid conflicts.

Integration points: macro names/signatures, class names, `{% block head %}`, `NavItem` shape, `pager` params, `?q=`/`page` URL parameters.

## Test strategy
- Part 1 `tests/test_ui_components.py`: render macros via the Jinja env: `pager` (single page shows count only, ellipsis for many pages, current page marked, params preserved, `total=0` renders nothing), `tabs` (`aria-current` only on active), `pill` tones, `page_header` (breadcrumb last item not a link, CTA present), `empty_state`, `icon` unknown name raises a clear error or renders nothing (decide and test). Nav test: groups and labels present, active item marked, every item with `term_key` shows its glossary sub-line, skip link and `lang="nl"` present. No external URLs in `base.html` output.
- Part 2: tests for `?q=` (matches number/description/reference, case-insensitive, `%` and `_` literal, combined with `dagboek` and pagination, pager links keep params), page clamping (`page=0`, `page=999`), empty-state text for no entries vs no match. Domain test for `list_entries(q=...)` (money-free but touches ledger; write first).
- Part 3: relations pagination/total and combined filters; inbox tabs counts still correct; review page still renders all fields and flags; upload and extraction flows unchanged (existing tests).
- Glossary: extend `PAGES` in `tests/test_plain_language.py` for every redesigned page and run `assert_plain_language`; keep the "no unused glossary key" test green (nav sub-lines and tooltips still emit every key).
- Manual/visual check by the reviewers: run `./boekhouden`, open each screen at 375/768/1280px in light and dark, tab through with keyboard.

## Risks and decisions made
- Dribbble reference unreachable: decision, rely on the two screenshots; the spec is explicit enough to build without it.
- Plain-language tests scan HTML and ignore `td`, `nav`, `aside`, `option`: moving text into new wrappers (cards, tabs, pills) can make a term appear in a visible element without an `info()`. Mitigation: run `tests/test_plain_language.py` after every template change; keep the `info()` right next to every term, including in tab labels and card titles.
- Icon-only actions can hurt "usable without bookkeeping knowledge". Decision: icon actions always have `aria-label` and plain-Dutch `title`; the primary action per row on inbox keeps a visible text label.
- Parallel parts could drift from the contract. Decision: contract is in this spec; part 1 merges first; a reviewer checks screens only use contract classes (grep for unknown class names in templates).
- Tooltip clipping inside `overflow-x: auto` table wrappers: part 1 must verify tooltips in `th` cells are visible (fixed positioning by JS), with a CSS fallback that still reveals the text on focus.
- Search stays server-side (URL holds state, works without JS); the client-side filter in `app.js` is only for short static lists (grootboek/dagboeken).
- Brand color/name: default calm indigo and "Boekhouden"; easy to change later through `--primary` tokens. No business question needed.
- Sidebar grouping labels ("Verwerken", "Verkoop en inkoop", "Aangifte en overzicht") are plain Dutch and contain no glossary terms; "BTW" and "Inkoop"/"Verkoop" remain in the BARE_OK list for nav.
