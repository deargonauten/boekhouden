VERDICT: PASS
## Summary
`uv run pytest -q`: 341 passed. Checked acceptance criteria 1-28 against code and tests: glossary, info macros/global (`explain`, `next_info_id`), sidebar `term_key` + sub-line, domain messages (items 18), suggestion helpers in `suggestions.py` (exported), single-source label tables used by routes, route-level messages, enforcement tests (`test_plain_language.py`, `web_helpers.py`, message lint) all present. Error codes and exception classes unchanged; no route/model changes. Business logic stays in domain; routes only wire defaults.

## Nice-to-have
- `app/web/ledger_routes.py` `_default_cash_account`: matches journals to accounts by substring of the account name ("bank"/"kas"); fragile if names change, harmless since it only prefills and returns "" on ambiguity.
- `app/web/__init__.py`: `next_info_id` is a process-global counter that grows forever; ids stay unique, only cosmetic.
- `suggest_account_code` fallback loops are three near-duplicate scans; could be one ordered candidate iterator.
- `InvalidKindError` message embeds the raw kind string in quotes (developer-ish) but is not user reachable via forms.
