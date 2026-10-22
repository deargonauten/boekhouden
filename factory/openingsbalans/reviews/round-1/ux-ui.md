VERDICT: REWORK

## Summary
The main flow uses clear Dutch questions, sensible defaults and shared UI components. One blocking gap remains in the requirement that people can use it without bookkeeping knowledge. Review based on the diff and supporting code; the supplied full-suite result was accepted without rerunning it. Mobile layout was inspected in code only.

## Blocking findings
- [P2] app/web/templates/opening/form.html:56 and :76: Amount inputs are identified only by technical account names, including “Cumulatieve afschrijvingen”, “Kruisposten” and “BTW rekening-courant”. These terms have no glossary entries or adjacent explanations. Existing terms such as “voorbelasting” also appear without their explainers. Users must understand bookkeeping to decide where to enter their starting amounts, violating CLAUDE.md’s explicit global requirement. → Lead these rows with plain Dutch labels and provide glossary-backed explanations for their bookkeeping/tax terms. Add coverage for rendered account labels; the current plain-language helper excludes table contents.

## Nice-to-have
- app/web/templates/opening/form.html:88: After creating a “Nieuwe relatie” in another tab, existing contact selectors remain stale. Provide a refresh action that preserves entered amounts and invoice rows.

STATUS: DONE