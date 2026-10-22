VERDICT: REWORK

## Summary
Reviewed the delta against F.md. Separate line columns, phone stacking, numbered due-date hints, checkbox alignment and label associations address the reported problems. No blocking htmx issue found by inspection.

Used the supplied result: 2228 passed, 1 deselected. No tests rerun; browser rendering was not independently verified.

## Blocking findings
- [medium] app/web/static/css/sales.css:45: Below 69rem, the clipped table header hides the only glossary explanation buttons for “BTW-tarief” and “Omzetrekening”. Replacement labels contain only jargon, leaving phone users without accessible explanations and violating the global plain-language requirement. → Keep glossary explanations visibly accessible in the stacked layout, using real labels or a shared explanation area outside the hidden header.

## Nice-to-have
None.

STATUS: DONE