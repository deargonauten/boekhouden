VERDICT: REWORK
## Summary
The checklist, period navigation and advisory banners fit the existing UI. Two usability issues need correction. Reviewed code against the spec and accepted the supplied result of 2671 passing tests; visual browser verification was unavailable.

## Blocking findings
- [medium] app/web/templates/controle/index.html:6: The unbalanced-booking warning uses “debet”, “credit” and “storno”, but its only explainer describes an unbalanced booking without explaining those terms. → Render the existing glossary explainers beside the warning, or use plain Dutch throughout. Include this warning state in plain-language coverage.
- [high] app/domain/checks/service.py:221: “Voeg het stuk toe via de inbox” gives no workable way to attach a receipt to the flagged existing booking. The booking page has no attachment action, and booking the uploaded receipt creates another booking, risking duplicate expenses. → Provide an accurate, supported recovery path that avoids duplicate booking, with a link and explicit steps; verify that following it resolves the warning.

## Nice-to-have
None.

STATUS: DONE