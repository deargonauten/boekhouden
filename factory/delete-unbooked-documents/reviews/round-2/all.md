VERDICT: PASS

## Summary
Both previous blocking findings are resolved. App-wide middleware rejects foreign-origin and cross-site mutation requests before deletion; targeted tests verify that rows and files remain intact and legitimate requests succeed. The booked-document page now explains “storno” in plain Dutch and includes the central glossary tooltip for both GET and rejected POST states.

Reviewed `git diff HEAD~2...HEAD`. No blocking security, correctness, UX or UI regressions found in the delta. Used the supplied result: 1717 passed, 1 deselected; no full-suite rerun or browser verification.

## Nice-to-have
- app/web/templates/inbox/list.html:95: Add `info("bewaarplicht")` beside the new row hint so its explanation is accessible without opening the upload modal.

STATUS: DONE