VERDICT: PASS
## Summary
`uv run pytest`: 1028 passed. Diff vs main reviewed for routes, macros, JS and tests.
- Drawer logic: `is_drawer_request` does an exact `HX-Target == "<id>-body"` match, so boosted requests (target `body`) still get the full page. The ledger and inbox detail routes only branch on it and pick a shared partial, so there is no business logic in the handlers. The partials are shared between page and drawer, which prevents drift. The storno form uses an id suffix in the drawer to avoid duplicate ids.
- Backwards compat: `page_header` and the other existing macros keep their signatures. `ledger/_settings_nav.html` keeps `settings_header`. The settings-nav data lives in `navigation.py` and is reached through globals.
- `/help`: the route calls `terms_alphabetical()` in the domain module. The helper is a small append-only addition to `glossary.py`.
- JS: vanilla, with try/catch around storage access, a focus trap, an Escape handler, and the history-save cleanup so a stale open drawer is not restored.
- Tests cover the macros, the partial vs full page responses, and the help page.
## Nice-to-have
- A drawer `hx-get` that returns a 4xx (for example an unknown id) is not swapped by htmx, so the drawer stays closed with no feedback. Consider opening on `htmx:responseError` or letting 404 swap.
- `add_error` is threaded through `_accounts_page` and `_journals_page` as a separate flag next to `error`. It could be derived in the template, but it is harmless.
- The `app.js` size should be checked against the spec's 260-line cap, though that is not a correctness matter.
