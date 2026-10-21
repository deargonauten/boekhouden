VERDICT: REWORK
## Summary
The flows cover the user stories well: entry list/filter/paging, entry form with preserved input, Dutch errors and 422/409 mapping, storno only when reversible, settings pages, a permanent-lock confirm. 201 tests pass. One real usability bug on the Boekjaren page: its error responses are never shown.

## Blocking findings
- [medium] app/web/templates/ledger/fiscal_years.html:9,18,35 (create-year, afsluiten, vergrendel forms): these forms lack `hx-boost="false"`, unlike every other form in the feature. `base.html` sets `<body hx-boost="true">`, and htmx does not swap 4xx responses by default (no `htmx:beforeSwap` override exists). `_years_page(..., status=409)` therefore renders the error but the user sees nothing happen. Most likely case: after creating the current year the input still defaults to `current_year`, so clicking "Boekjaar aanmaken" again (YEAR_EXISTS, 409) silently does nothing. The same applies to a failed lock or close. Done looks like: 4xx responses on these forms are visible to the user. Simplest: a small global `htmx:beforeSwap` handler (in a static JS file loaded by base.html) setting `shouldSwap=true` for 409/422, which keeps `hx-confirm` working; alternatively drop boost on these forms and replace hx-confirm with an inline `onsubmit="return confirm(...)"`. Add a web test that posts a duplicate year and asserts the Dutch message is rendered. Optionally default the year input to the first year without a boekjaar.

## Nice-to-have
- entry_form.html: errors are shown in a box at the top; the totals/difference are only in the tfoot after submit (as specced), so on long forms the user must scroll. Fine for now.
- Storno form: the date input has no hint that empty means "same date as original, or today if locked".
- Accounts page offers no rename and no delete, although spec criterion 13 allows both in the domain; only the toggle is exposed in the UI (spec criterion 23 only requires toggle and add).
- Journal type column shows raw values (`verkoop`, `bank`) rather than the Dutch labels used elsewhere.
- Entries list shows the "Storno van" badge but `/boeken` filter has no empty-result message distinct from "no bookings at all".

STATUS: DONE
