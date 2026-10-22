VERDICT: REWORK

## Summary
The core booking logic uses integer cents, balanced entries, guarded payment updates, and append-only matches. Two reversal issues remain. Reviewed against the spec and supplied result of 1964 passing tests; no full-suite rerun.

## Blocking findings
- [high] app/web/templates/bank/reconcile_detail.html:139: “Bekijk de boeking” exposes the existing ledger reversal form. Its `/boeken/{id}/storno` handler calls `ledger.reverse_entry` directly, leaving the transaction `geboekt`, matches active, and invoices marked paid after their payment entry is reversed. Reconciliation undo then fails because the entry is already reversed. → Route reconciliation-entry reversals through reconciliation undo, or reject generic reversal with a clear link to that action. Enforce this server-side and add an integration test covering payment status and matches.

- [medium] app/domain/reconcile/service.py:631: Undo calls `reverse_entry` without a booking date. That function falls back to today when the original period is locked, so undo succeeds if today has an open period, contrary to AC 11. Existing locked-period tests miss this because the fallback date has no open period or all periods are locked. → Explicitly reject undo when the original period is locked, and test with a locked original period plus an open period containing today.

## Nice-to-have
None.

STATUS: DONE