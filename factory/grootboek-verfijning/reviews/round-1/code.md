VERDICT: PASS
## Summary
Reviewed `git diff main...HEAD` against the spec. Full suite: 1289 passed. Migration 0007 adds the columns with the right nullability and server defaults, backfills idempotently from seed modules (no model imports), and downgrades by dropping the columns. `default_contexts` follows criterion 2 and is shared with `add_account` and `set_account_contexts`. The vat domain (rate parsing in integers, catalogue validation, locked-period rubriek rule, deactivate-default rule with the 3-accounts-plus-"en nog N" message, GEEN protection, immutable rate) matches the exact messages in criterion 6. Routes are thin and map statuses as specified (409 for locked and default conflicts). Inbox `_ordered_accounts` uses `list_accounts_for("purchase")` plus selected accounts. The vat fallback only applies when `resolve_vat_code` finds nothing. Money stays in integer cents and basis points.

## Blocking findings
None.

## Nice-to-have
- `vat-suggest.js` on the inbox review: the btw select in `_review_line.html` has no `data-touched="1"` when the server pre-filled it (AI-extracted or inferred code). Changing the account on such a line therefore overwrites the extracted tarief with the new account's default. The manual form does set `data-touched` for a rendered value. Consider the same in the inbox for lines that already have a vat_code.
- `ledger_routes._accounts_page` recomputes the "locked" system-account set with `default_contexts` duplicating the check in `set_account_contexts`; a small shared helper in the ledger domain would avoid drift.
- `ledger/service.py` imports `app.seed` from the domain layer (spec-sanctioned, but note the coupling).
