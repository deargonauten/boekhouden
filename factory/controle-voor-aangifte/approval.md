VERDICT: HUMAN_REVIEW

## Reasoning
The process was followed: spec approved, builders A, B and C ran and were merged, integration is on the branch, and two review rounds ran (code round 1, ux-ui rounds 1 and 2). Round-1 ux-ui findings (unexplained debet/credit/storno terms; a fix path for "boeking zonder document" that did not exist) were fixed in round 2 and the round-2 ux-ui review passed. The test result in state.md is 2672 passed. I did not rerun the suite.

The implementation is sound on the money/VAT side: checks are read-only, period-scoped, use SQL aggregates, and the banner never blocks filing. The reason for HUMAN_REVIEW is one acceptance criterion that is no longer met as written, plus a product gap the human should decide on:

- Spec AC 7 requires each problem check to have a fix button. The `boeking_zonder_document` check has no fix button after round 2 (`fix_href`/`fix_label` are empty; the template renders the button only when `fix_href` is set). The round-2 fix made this deliberate, because the spec's fix path (attach a receipt to an existing booking) does not exist in the app. The copy is now honest and per-item booking links remain. This is a reasonable call, but it departs from the spec, and the spec's stated goal ("bookings without a receipt") is now covered only by advice text.
- Visual verification was never done. Both ux-ui reviews note that no app was running on localhost:8000, so the banner, the controle page and the collapsed "Klopt" rows have not been seen in a browser.

Nothing found is a blocking correctness or security issue.

## Acceptance criteria check
1. `run_checks(session, period, *, today=None) -> CheckReport` in `app/domain/checks/`, exported from `__init__.py`, integer cents: met (build A report; code review round 1 PASS).
2. Each check returns the right count/level/items and ignores data outside the period: met per build A (26 domain tests) and code review. Not re-verified by me.
3. No data gives all checks `ok` and verdict `ok`: met per build A tests and build B `test_controle_web` (5x Klopt).
4. Storno, opening, inkoop/verkoop entries and entries with a linked document never appear in `boeking_zonder_document`: met per build A and code review.
5. `onevenwichtig` tested with raw inserts bypassing the ledger: met per build A.
6. `GET /controle` 303 to current VAT period; `GET /controle/{year}/{kind}/{number}` renders; invalid period 404: met per build B (tests/test_controle_web.py).
7. Page lists checks problems first with badge, count, explanation, up to 5 links, fix button; ok checks collapsed as "Klopt"; period switcher; link back to aangifte: partly met. Problems-first, badges, items, switcher and back link are in place. The fix button is NOT shown for `boeking_zonder_document` (deliberate, see above).
8. Sidebar nav "Controle", group 2, term_key `controle_aangifte`, path `/controle`, right after BTW, active on sub-paths: met (`app/web/navigation.py` line 34; build B reports nav tests green).
9. Banner on unfiled return (above "Controleer dit") and confirm page with the non-blocking sentence; none on filed returns; filing works with warnings: met per build C tests (8 tests) and code review.
10. All page text is plain Dutch with actionable messages: met per ux-ui round 1 and round 2 reviews, with the two fixes applied.
11. Plain-language: glossary entries added (`controle_aangifte`, `ongeboekte_transactie`, `bon_bij_boeking`, `onevenwichtige_boeking` confirmed in `app/domain/glossary.py`); `conceptfactuur` replaced by the existing `concept_factuur` term (spec allowed reuse); PAGES in `tests/test_plain_language.py` updated; round-2 added a data-term test for debet/credit/storno: met.
12. No writes on any route (GET only, no commit): met per build B test "GET writes nothing" and code review.

Spec deviations that are documented and accepted by the reviewers: `conceptfactuur` key replaced by existing `concept_factuur`; `onevenwichtige_boeking` explanation says "beide kanten" rather than naming debet/credit inside the explanation (the glossary test forbids it there, and the terms are explained next to the warning instead).

## Outstanding issues
- The code review was run only on round 1. The round-2 fix changed `app/domain/checks/service.py` (copy and emptied `fix_href`/`fix_label` for one check) and was covered only by the ux-ui round-2 review and the test run. Risk is low (copy and parameters only), but it was not code-reviewed.
- No browser check of the new page, banner or collapsed rows (no app on localhost:8000 during review).
- The "boeking zonder document" check cannot be resolved in-app: there is no way to attach a receipt to an existing booking. The copy tells the user to keep receipts in their own records and not to book them twice. A later feature could add an attach action, but that is out of scope here.
- Hrefs live in the domain as strings. The risk of drift is covered by web tests that follow the links, which build B reports as passing.

## What the human should look at
1. Decide whether dropping the fix button for "Boekingen zonder bon" is acceptable, or whether it should get a real attach-document action in a follow-up (spec AC 7 says every problem check has one).
2. Open `/controle/{year}/quarter/{n}` and the BTW-aangifte and indienen pages in the browser (run the app). Check the banner wording, the badge colours in the retro theme, the collapsed "Klopt" rows and that the debet/credit/storno info icons read well for a non-accountant.
3. Confirm the wording of the "boeking zonder document" advice is what the user wants: advisory only, "7 jaar bewaren", and "Boek de bon niet nog een keer".

STATUS: DONE
