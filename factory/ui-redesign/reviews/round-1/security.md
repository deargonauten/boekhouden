VERDICT: PASS
## Summary
Reviewed the diff vs main for XSS, query injection, unsafe JS and data exposure.
- Autoescape stays on. The only `|safe` is `paths[name]|safe` in `partials/_ui.html` (icon macro). It renders a static dict of SVG fragments. Every `icon()` call site uses a literal name or `NavItem.icon` (a constant), never user input. An unknown name raises.
- The new search `q` in `ledger.list_entries` goes through SQLAlchemy `ilike` with bound parameters. `\`, `%` and `_` are escaped with an explicit `escape="\\"`, so there is no injection and no wildcard abuse. Tests cover this. The relations `q` filter is in Python (`_matches`), not SQL.
- The pager builds URLs with `urlencode` (`page_url`), and Jinja escapes the result in `href`. The user-supplied `q` is re-rendered in the input `value` and the pager links, both escaped.
- `hx-confirm` and `onclick` strings are static or contain only ints (`y.year`, `p.number`). The one inline handler (`this.closest('tr').remove()`) is a constant. The new inline `<script>` is a constant. There is no `innerHTML` or `eval`.
- Pagination clamping is correct. No new secrets, logging or exposed data.

## Nice-to-have
- `app/web/relations_routes.py` (`contacts_list`): `page.strip().isdigit()` is true for characters like "²", and `int()` then raises ValueError, giving a 500. Use `try: int(page)` or declare `page: int` with a fallback. This is harmless on a local single-user app.
- `ledger_routes.entries_list`: `dagboek` is only used as a bound filter, so it is safe. It also feeds the journal-tab filter `j.code == dagboek`, which is fine.
- A very large `page` value is bounded by the clamp, so there is no unbounded offset.

STATUS: DONE
