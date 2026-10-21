VERDICT: PASS
## Summary
The ledger UI fits the existing design: it reuses the CSS variables, has a dark-mode block, and the sidebar layout is unchanged. Labels are Dutch and form fields have labels or aria-labels. Tables sit in `.table-wrap` with horizontal scroll, so narrow screens work. Error and empty states are present. `hx-confirm` dialogs guard the permanent actions. `uv run pytest` gives 201 passed. I read the templates, CSS and routes; I did not run the app in a browser.

## Nice-to-have
- `app/web/static/app.css`: `.content p { color: var(--muted) }` outranks `.alert` on `<p class="alert">`, so error text in `_error.html` renders muted instead of red. Fix with `.content .alert { color: var(--danger) }` or use a div.
- `.btn-danger` in dark mode puts white text on #f97066 (about 2.6:1 contrast). Use dark text or a darker red there.
- The lock-period and close-year forms stay boosted, and htmx does not swap 409 responses. A stale-page error would be silently dropped. This is rare; setting `hx-boost="false"` on them, or handling the response, would fix it.
- Journals list shows the raw type key (`verkoop`, `bank`) rather than a label. The account type select in the add form is labelled, but the journal list is not.
- The entry form has no inline running total before submit. The spec allows server-side totals on submit only, so this is fine.

STATUS: DONE
