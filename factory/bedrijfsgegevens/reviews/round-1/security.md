VERDICT: PASS
## Summary
Security lens, feature bedrijfsgegevens. No blocking issues.
- Output encoding: Jinja2Templates autoescapes by default; user values go into quoted attributes via `{{ }}` and no `|safe` is used in the company template or in the notice/error_box macros. Error and missing-field messages are static domain strings.
- Injection: all persistence goes through the SQLAlchemy ORM (session.get / setattr); no raw SQL. Migration uses fixed CHECK constraints.
- Input validation: done in the domain (kvk, btw-id, iban, postcode, country, email, legal_form, name length); DB CHECKs are a second layer. Single-row enforced with CHECK (id = 1).
- Secrets / logging: no secrets, nothing sensitive logged, no external calls added.
- Authn/CSRF: single-user localhost app with no auth model, consistent with the rest of the app (relations routes work the same way); not in scope for this feature.
- The only GET parameter (`opgeslagen`) is compared to "1" and never echoed.
## Nice-to-have
- address_line, city, phone and trade-name-like free text fields have no server-side length cap (only legal_name/trade_name at 200). Harmless locally; a generic max (e.g. 200) would be tidy.
- No CSRF protection on POST (app-wide, localhost-only; revisit if the app is ever exposed beyond localhost).

STATUS: DONE
