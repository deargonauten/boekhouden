VERDICT: PASS
## Summary
Security lens, round 1. Local single-user app, no authn/multi-user model, so the relevant checks are input validation, injection and data integrity.
- All new routes (btw-codes CRUD, account vat default/contexts) use SQLAlchemy ORM with bound parameters; no raw SQL or string-built queries.
- Input is validated in the domain layer (code regex fullmatch, rate parsing with bounds, rubriek whitelist against catalogues, vat code must exist and be active, unknown account -> 404). Rubriek and rate use integer arithmetic.
- Templates rely on Jinja autoescape; user-supplied name/code are rendered escaped. The htmx suggestion endpoint only echoes whitelisted catalogue options.
- Integrity: rubriek changes are blocked for codes used in locked periods; system-account contexts cannot be altered; deactivating a code that is a default is refused. Handlers roll back on error, no commits in domain.
- No secrets, logging of sensitive data or new dependencies. vat-suggest.js uses no innerHTML.
- Test suite: 1289 passed.
## Nice-to-have
- Changing a vat code's rubriek in a still-open period silently re-classifies existing lines in the next BTW-aangifte; acceptable (periods lock), but a warning could help.
- POST routes have no CSRF protection; consistent with the existing localhost single-user design.
STATUS: DONE
