VERDICT: PASS
## Summary
Security lens, local single-user app bound to 127.0.0.1 (app/config.py), no auth by design. Checked:
- Injection: the only raw SQL (`_next_number`, service.py) uses bound parameters. All other queries use the SQLAlchemy expression API. No string-built SQL.
- XSS: Jinja2Templates with default autoescape. No `|safe`, `Markup` or autoescape overrides in app/. Error messages render via `{{ error }}`.
- Input validation: ids are checked with `.isdigit()` before `int()`. Amounts go through `parse_euro` into integer cents. Dates use `fromisoformat`. Account and journal types are validated in the service. Routes use `:int` path converters.
- Data integrity: append-only and period-lock rules are enforced by DB triggers (migration 0002) as well as the service. Storno goes through the service.
- Secrets and logging: nothing sensitive is added or logged.
- Dependencies: none added.

## Nice-to-have
- CSRF: state-changing POSTs (post entry, storno, lock period, close year) have no CSRF token or Origin check. A malicious webpage open in the user's browser could blind-POST to localhost:PORT. Low likelihood for a local tool. A cheap Origin/Host-check middleware would be a good hardening step later, and a DNS-rebinding Host check along with it.
- `year: int = Form(...)` in `years_create` accepts arbitrarily large values. An absurd year could cause date errors or a 500. Bound it, e.g. 1990-2100.
- `page` is only clamped to >= 1. A huge value gives a large OFFSET, which is harmless in SQLite.

STATUS: DONE
