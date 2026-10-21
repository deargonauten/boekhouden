VERDICT: PASS
## Summary
Reviewed the integrated branch against all 27 acceptance criteria and the CLAUDE.md domain rules. `uv run pytest` gives 201 passed. Money is int cents throughout, with explicit bool/float rejection. Balance is validated in a single posting path. Immutability, period locks and one-way status changes are enforced by DB triggers with raw-SQL tests. Sequence numbers are gapless per (journal, boekjaar): the sequence bump runs inside a savepoint, and validation runs before any write. Storno, the double-storno and storno-of-storno guards, the locked-period fallback date and the derived "gestorneerd" status all match the spec. Routes only parse, delegate, map errors and render, and the 303/422/409/404 mapping matches the spec.

`alembic check` run by hand against the default `data/boekhouden.db` reports "not up to date". That is only because the local dev DB has not been upgraded, not a drift problem. The migration test suite covers check/up/down on tmp DBs.

Documented deviations by the builders are reasonable:
- Storno skips the active checks on accounts, VAT codes and dagboek, so a storno stays possible after deactivation.
- `post_entry` rejects `kind="storno"`.
- Extra error codes were added.
- RGS codes are mostly NULL, per the "do not invent" rule.

## Nice-to-have
- `app/domain/ledger/service.py` `create_fiscal_year`: a year outside 1..9999 (for example `year=0` posted to `/instellingen/boekjaren`) raises a bare `ValueError` from `date()`, which gives a 500 instead of a Dutch 422. Add a range check that raises a `LedgerError`.
- `app/web/ledger_routes.py` `years_create`: `year: int = Form(...)` returns FastAPI's raw 422 JSON for a non-numeric value. Consider parsing it as a string.
- `service.py` `set_account_active` and `set_journal_active`: system accounts such as debiteuren and btw can be deactivated, which would break later features that post to them. Consider blocking this or warning.
- `service.py` `list_entries`: the total comes from `sum(debit)` through a group-by subquery. This is correct, but the pagination count and the main query are built separately, so keep them in sync when adding filters.
- `rename_account` and `delete_account` have no UI. The spec only requires the functions, so this is fine.

STATUS: DONE
