VERDICT: APPROVE
## Reasoning
Process followed: spec approved (state/commit e182b3a), parts 1-7 built in worktrees and merged in the spec's order, integration commit, review round 1 (code, security, ui, ux) all PASS with no blocking findings. Full suite re-run by approver: 1289 passed. Diff touches only the spec's owned files plus tests. Migration 0007 and models are covered by migration tests (upgrade/downgrade/backfill/drift). The unit-test "alembic check" passes via the test suite; running `alembic check` against the local dev DB only reports it is not yet upgraded, which is expected (apply `alembic upgrade head` before use).

## Acceptance criteria check
1. Migration columns + models + head 0007: met (tests/test_migrations.py, test_grootboek_migration.py).
2. Backfill of rubrieken and account contexts via seed modules, shared `default_contexts`: met (parametrised tests).
3. `default_vat_code` stays single field: met.
4-6. Rubriek catalogue, `suggest_rubrieken`, vat service (add/update/toggle/usage/rubriek_for), integer rate parsing, exact Dutch error messages, locked-period and default-code rules: met per code review and tests/vat.
7-10. Ledger helpers (`set_account_vat_default`, `set_account_contexts`, `list_accounts_for`, `suggest_vat_code`, `add_account` flags): met.
11. Btw-codes settings page, nav item, modals, routes, status mapping (400/409): met.
12. Grootboek columns and add-modal defaults: met.
13. Manual boeking `data-vat` + vat-suggest.js with data-touched: met.
14. Inbox review limited to purchase accounts, selected kept, vat fallback from account default: met.
15. No raw exception text, errors in error_box: met.
16. Glossary entries (rubriek, standaard_btw, selecteerbaar_bij, voorbelasting, kor), plain-language PAGES tests: met.
17-18. Suggested defaults and plain-Dutch labels with info icons: met.

## Outstanding issues (all nice-to-have, acceptable to ship)
- Inbox review: btw select is not marked `data-touched` when server-prefilled, so changing the account on such a line can overwrite an extracted tarief (e.g. 9% to 21%). This is a small correctness/UX risk with real invoices; worth a quick follow-up fix (set data-touched="1" when line.vat_code is set).
- Duplicated system-account check in `ledger_routes._accounts_page` vs `set_account_contexts`.
- Two Opslaan buttons per Grootboek row; a changed checkbox without saving is lost.
- Lock explanation only as title tooltip; identical aria-labels on btw-code icon buttons.
- Rubriek change in an open period reclassifies existing lines silently (periods lock; acceptable).
- No CSRF, consistent with the existing localhost design.

## What the human should look at (if HUMAN_REVIEW)
Not applicable. Optionally glance at the Grootboek table (7 columns) visually and consider the data-touched follow-up.

STATUS: DONE
