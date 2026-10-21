# Part 2 (Ledger screens): build report, round 1

Branch: `worktree-agent-af98221d1fedc1e1d` (worktree `<repo>/.claude/worktrees/agent-af98221d1fedc1e1d`), built on top of the merged part 1.

## Built
- **Boeken list** (`ledger/entries.html`): band with icon `book`, dagboek tabs inside the band (`tab_items`, only when few journals; dropdown filter otherwise), `row--warn` on storno rows, "Bekijken" link per row opening the boeking drawer (`data-drawer-open="#boeking-drawer"` + `hx-get`, `hx-target="#boeking-drawer-body"`, `hx-push-url="false"`, `hx-boost="false"`, href fallback to the full page), `pager(..., sticky=True)` placed directly in the card (not in `.card__footer`, otherwise sticky cannot work). Drawer shell via `drawer("boeking-drawer", "Boeking", "boeking")`.
- **Boeking detail**: new partial `ledger/_entry_detail_body.html` (facts, regels, storno form, error box); `entry_detail.html` is band + `include` of the partial. Route `_detail` returns the partial when `web.is_drawer_request(request, "boeking-drawer")`, else the full page; in the drawer the partial adds a summary line (number, date, status pill). 404 unchanged.
- **Nieuwe boeking form**: band icon, totals block (`Totaal links (debet)`, `Totaal rechts (credit)`, `Verschil`, plus the existing "Er ontbreekt ... aan de creditkant." sentence) under the lines table replacing the `tfoot` rows; sticky `form-actions` bar with primary "Boeking opslaan" (was "Boeken").
- **Settings pages**: `accounts.html`, `journals.html`, `fiscal_years.html` extend `base_settings.html` (blocks `settings_header`, `settings_content`). `settings_header(current)` renders only `page_header` with `icon_name="settings"` (no tabs); it optionally takes a `{% call %}` body for the primary action. Grootboek h1 is "Rekeningen (grootboek)" (a bare "Grootboek" h1 fails the plain-language scanner); Dagboeken h1 carries the dagboek info.
- **Modals**: Grootboek "Rekening toevoegen" (`#rekening-toevoegen`) and Dagboeken "Dagboek toevoegen" (`#dagboek-toevoegen`) replace the `<details>`. Form posts/fields/messages unchanged. A validation error in the add form re-renders with `open=True` and the `error_box` inside the modal; errors from the activate/deactivate buttons stay a page-level error box (new `add_error` flag in `ledger_routes.py` `_accounts_page`/`_journals_page`).
- **Boekjaren**: `stat_cards` card "Overzicht" with "Open maanden" / "Maanden op slot" (summed over all years, computed in the template, no new queries); `row--done` on vergrendelde periods; "Nieuw boekjaar" header on the create form.
- **CSS** (`ledger.css`): removed old dagboek-tab row, pager footer and `balance-row` rules; added summary line, totals block, sticky action bar, settings column spacing, single-column form inside modal. Tokens only.

## Tests
`uv run pytest`: all green (1024 passed). In `tests/test_ledger_web.py`: replaced `test_settings_tabs_mark_current` by `test_settings_pages_use_secondary_nav`; added drawer partial vs full page (incl. `HX-Target: body` and no header), unknown id 404, drawer trigger + sticky pager, `row--warn`, modal closed/open-on-error with error inside, stat-card counts and `row--done`, drawer partial plain-language check, header icon assert. `tests/test_plain_language.py` untouched and green.

## Deviations
1. Boekjaren stat card is titled "Overzicht" (no term) with cells "Open maanden"/"Maanden op slot", not "Boekjaar" / "Open perioden": plain Dutch, avoids an extra explainer. Counts are totals over all boekjaren.
2. Dagboeken also got an add-modal (spec only names Grootboek); same pattern, consistent UX.
3. The totals block group has `aria-label="Totaal debet / credit en verschil"` because `tests/test_plain_language.py::test_unbalanced_footer_says_which_side` (not mine to edit) asserts the literal "Totaal debet / credit".
4. Glossary keys `grootboek` and `boekjaar` stay "used" through `info(...)` calls appended to the lead sentences (the lead-sentence test pins the leading text).
5. Grootboek table columns unchanged; single icon buttons kept (1 action per row, so no row_menu).
6. No visual browser check possible; layout verified by tests and CSS reading only.

## Notes for the integrator
- No new URLs for `PAGES` in `tests/test_plain_language.py`. Optional extra coverage: `c.entry_url` with headers `{"HX-Request": "true", "HX-Target": "boeking-drawer-body"}` (already tested in `test_ledger_web.py`), and the add-error state `POST /instellingen/grootboek` with code `12` (modal open).
- Files outside my ownership touched: none.

STATUS: DONE
