# Round 2 fix: controle-voor-aangifte (ux-ui REWORK findings)

Branch: worktree-agent-a7771f2afbbe68e83

## 1. Unbalanced-booking warning (medium)
Chose to render the existing glossary explainers: `check_info("onevenwichtig")` now also shows `info("debet")`, `info("credit")` and `info("storno")` next to `onevenwichtige_boeking`. The required wording "Debet en credit zijn niet gelijk: er ontbreekt EUR12,10" is kept (CLAUDE.md example, existing test).
Test: `tests/test_plain_language.py::test_controle_page_with_unbalanced_booking_is_plain_language` renders the /controle page with a real unbalanced entry and runs assert_plain_language plus data-term checks for debet, credit, storno (red before, green after).

## 2. boeking_zonder_document fix path (high)
Investigation: `Document.journal_entry_id` is only set by the purchase booking flow (booking a document creates a new entry). No route or domain function links a document to an existing booking, and the booking page has no attachment action.
Chose: do NOT build an attach feature. Copy rewritten to be honest: it is advice only, you can still file, keep the receipt with your own records (7 years), open the booking from the list and check it, and "Boek de bon niet nog een keer" (duplicate expense). The fix button is removed for this check (`fix_href`/`fix_label` are empty strings; the template renders the button only when `fix_href` is set). Per-item links to the booking remain.
Test: `tests/checks/test_checks.py::test_manual_expense_without_document_is_reported` asserts empty fix_href/fix_label, no "inbox" mention, and the "niet nog een keer" warning.

## Files
app/web/templates/controle/index.html, app/domain/checks/service.py, tests/checks/test_checks.py, tests/test_plain_language.py

## Tests
See final message for the full-suite result.
