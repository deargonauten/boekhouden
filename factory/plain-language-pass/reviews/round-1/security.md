VERDICT: PASS
## Summary
No security issues. Tooltip text comes only from the static glossary (`app/domain/glossary.py`) and is rendered through Jinja autoescape (Starlette Jinja2Templates, .html); there is no `|safe` or `Markup` anywhere in app/. Macro keys are literals chosen in code, never user input; `title="{{ t.explanation }}"` in the sidebar is escaped in an attribute context. User-supplied values (account names, descriptions) in the changed templates remain escaped. The new `next_info_id` counter and `explain` globals expose no data. Route changes (default journal, suggested account code, fiscal year) only read the DB and add stricter validation (debit xor credit). Money stays integer cents. No new dependencies, secrets, or logging.
## Nice-to-have
- `_info_ids` is a process-global itertools.count; fine for single-user, but ids grow unbounded (harmless).
- `get_term` raising on an unknown key would produce a 500 at render time; the tests cover glossary keys, so acceptable.
STATUS: DONE
