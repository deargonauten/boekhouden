VERDICT: APPROVE

## Reasoning
- Process: spec approved (`Status: APPROVED`). Build A (domain + data, c7f42b3) and build B (screens, glossary, wiring) were delivered on disjoint files. Review round 1 returned two REWORK verdicts: a write-race in `book_opening_balance` (code-security) and plain-language gaps in the account rows (ux-ui). The round-2 fix (6e85ac7) addressed both, with regression tests for each. Round 2 (`reviews/round-2/combined.md`) returned PASS. That is within the two-round maximum, and both blocking findings are closed.
- Race fix: the write lock (`_open_transaction`) is now taken before the active-entry lookup and the replacement checks, in the same transaction as the writes. The interleaved-session test `test_overlapping_first_submissions_leave_one_active_entry` covers AC 7 and AC 9.
- Plain language: account rows lead with plain Dutch, followed by the code and name, then an info icon. New glossary terms were added and the account-row test was extended. This addresses the CLAUDE.md global requirement that was the blocking gap in round 1.
- Tests: the orchestrator reports 1818 passed, 1 deselected (state.md, 2026-10-22). The suite was not rerun for this approval, as instructed. Build A reported 1784 and build B reported one glossary failure that was reworded and re-run. Both are superseded by the 1818 result.
- Scope note: the builders touched a few files outside their owned lists (`tests/test_migrations.py`, `tests/bank/test_migration.py` assertion removal, `app/web/navigation.py`, `tests/test_help_page.py`). The reports describe each as trivial and unavoidable. None of them weakens money or VAT logic.

## Acceptance criteria check
Criteria are taken from `spec.md` section 4. The status comes from the build and review reports. Code was not spot-checked line by line for every item.

Domain rules
1. Target boekjaar (first boekjaar, start date, the AC 1 messages, NOT_FIRST_YEAR): met (build A, service tests).
2. Input types `OpeningInput` / `OpeningItemInput`, integer cents: met.
3. Allowed balance accounts (asset/liability, excludes 1300/3000/equity, negative allowed, plain message): met.
4. Line rules (sign rules, debiteur 1300, crediteur 3000, vermogen on 2000 with three cases, no vat_code): met (pure tests in `tests/opening/test_build.py`).
5. Entry fields (memoriaal, kind opening, description, source_type/source_id, plain messages): met.
6. Openstaande post validation (contact, number, dates, amount > 0, duplicates, flag set on booking): met, with plain messages. The builder's extra messages are plain Dutch and were not in the spec.
7. One active beginbalans per boekjaar, aanpassen instead of a second: met (race fixed in round 2).
8. Aanpassen = storno + new entry, locked period refused, paid items refused, UNCHANGED no-op: met.
9. Atomic (savepoint, no entry number consumed on failure): met (tests for locked period and mid-way failure rollback).
10. Read model `get_opening_balance` (view, rows, items with status, totals): met.
11. Trial balance (1300, 3000, 2000 match, debit = credit): met (test in service suite).

Crediteuren integration
12. `open_by_supplier` includes open crediteur posten, `opening_count`, 3000 = total open: met (`tests/purchase/test_opening_items.py`).
13. `list_opening_items(session, side, open_only)`: met.

Web / UX
14. Settings tab "Beginbalans", page title, three cards, helper texts, HTMX row add, controle summary, button text: met per the builder B report and round-2 review.
15. `/inkoop` block with "te laat" pill and "waarvan n uit beginbalans": met (per report).
16. POST books and redirects with notice; 422 keeps values and shows error_box: met (`tests/test_opening_web.py`).
17. Existing beginbalans shows boeking link and status pills; read-only with the locked note: met.
18. Entry detail link "Bekijk beginbalans": met.
19. No-boekjaar state with link; mobile stacking via existing components: no-boekjaar state met. Mobile layout was reviewed in code only, not in a browser.

Plain language (CLAUDE.md)
- Glossary terms `beginbalans`, `openstaande_post`, `beginbalans_aanpassen`, `eigen_vermogen_berekend` exist. The `beginbalans` detect pattern excludes the seeded account name: met.
- Reused terms are in the glossary. Round 2 added `cumulatieve_afschrijvingen`, `kruisposten`, `btw_rekening_courant`, `btw_af_te_dragen`.
- `tests/test_plain_language.py` includes the new pages: met.
- Plain-Dutch errors for the spec messages: met.

## Outstanding issues
Nice-to-have items from review round 2. None is blocking.
- Account labels for 1410, 3130 and 3140 in `ACCOUNT_TERM` (`app/web/opening_routes.py`, around line 159) are not specific enough. "De klant rekent de BTW af" does not separate recoverable from payable reverse-charge VAT, and the 3140 explanation discusses sales, not private use. Wording should be tightened in a follow-up.
- After "Nieuwe relatie" is created in another tab, the contact selectors on the form stay stale until the page is reloaded. A refresh action that keeps the entered amounts and rows would help.
- The vervangen status is never shown on the page, because `get_opening_balance` only returns the active entry's items. This matches the design and is not a defect.
- Mobile layout and the visual feel of the three cards were checked from code only. The round-2 review did not run the app.
- Builder A's deviations (extra error code `SYSTEM_ACCOUNT_MISSING`, `year` argument on `book_opening_balance`, per-side numbering in item labels, append-only triggers on `opening_item`) go beyond the spec. They are backward compatible and tested.

## What the human should look at (if HUMAN_REVIEW)
Not required for APPROVE. A quick look at `/instellingen/beginbalans` at phone width is worth doing before the feature is relied on. It was never rendered in a browser. The wording of the three account explainers above is also a reasonable thing to read as a non-accountant.

STATUS: DONE
