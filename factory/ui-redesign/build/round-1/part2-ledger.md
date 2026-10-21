# Part 2: ledger screens (round 1)

Branch: worktree-agent-aaac36615382640f1

## Built
- `ledger.list_entries(..., q=None)`: case-insensitive match on entry_number / description / reference, `%` `_` `\` escaped (literal), blank q ignored; a page beyond the last now clamps to the last page (in the domain, so `Page.page` is the page shown). Tests first: `tests/ledger/test_list_entries_search.py`.
- `ledger_routes.py`: `/boeken` takes `q`, `PER_PAGE = 50` (monkeypatchable in tests), `MAX_JOURNAL_TABS = 6`; passes active journals (+ the selected one if inactive) and `use_tabs`. No other route logic changed.
- Templates (`templates/ledger/*`): entries (page_header, card with dagboek tabs or a select when > 6 journals, search, table with pills, pager with noun "boekingen", empty states "Je hebt nog geen boekingen" / "Geen boekingen gevonden" + "Wis filters"), entry_detail (cards Gegevens / Regels / Ongedaan maken, pills, error_box), entry_form (cards Algemeen / Regels, `.field`s, error_box list, balance tfoot restyled only, form-actions), `_settings_nav.html` is now a macro `settings_header(current)` (page_header "Instellingen" + breadcrumb + tabs), accounts / journals (collapsible "toevoegen" card, client-side search via `data-filter-table`, Actief/Inactief + Systeem pills, icon buttons with aria-label + plain-Dutch title), fiscal_years (card per year, Open/Afgesloten and Open/Vergrendeld pills, lock icon buttons keep hx-confirm, danger "Boekjaar afsluiten" in card header, empty state). `_error.html` now uses `error_box`.
- `static/css/ledger.css` (tokens only), linked via `{% block head %}`.
- Tests added/updated in `tests/test_ledger_web.py` (search, literal % and _, combined filters, pager count + params preserved, page clamp 0/-4/999, empty states, storno pills, tabs, settings tabs, period pills, css served). `test_entries_empty` aria-current count 1 -> 2 (sidebar + active "Alle" tab).

## Tests
`uv run pytest -q`: 971 passed (1 deselected, pre-existing). `tests/test_plain_language.py` passes unchanged.

## Deviations / notes
- Account/dagboek client-side filter points at a wrapper (`#account-groups`) since app.js does one `querySelector` and then `querySelectorAll("tbody tr")`; groups with no visible rows are hidden by a `:has()` rule in ledger.css. Without JS the search box does nothing (progressive enhancement).
- Row action on grootboek/dagboeken is pill + icon button (archive/restore icons), not a switch.
- Tab labels "Grootboek / Dagboeken / Boekjaren" carry `info()` through the tabs macro (inside `<nav>`, so not scanned by plain-language tests, but the glossary keys stay used). Section h2 keeps `term_label(...)`.
- Hint on the new-booking form mentions "memoriaal" with `info("memoriaal")`; no new glossary entries.
- Page clamp ("beyond last shows last") lives in the domain `list_entries`; the route only clamps `page >= 1`.
- Not checked visually in a browser (no screenshots); layout verified by markup and tests only.

## For the integrator: URLs to add to PAGES in tests/test_plain_language.py
Existing ones still apply (/boeken, /boeken/nieuw, entry detail, storno detail, /instellingen/grootboek, /dagboeken, /boekjaren). Add:
- `/boeken?q=test` and `/boeken?q=bestaatniet` (no-match empty state)
- `/boeken?dagboek=MEM`

STATUS: DONE
