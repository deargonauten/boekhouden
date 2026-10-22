VERDICT: REWORK

## Summary

The import flow provides clear Dutch guidance, sensible defaults, explicit confirmation, and useful duplicate warnings. Shared components keep the screens consistent with the existing interface. One glossary gap violates the global plain-language requirement.

Reviewed the diff, specification, and build reports. Used the supplied test result: 1659 passed, 1 deselected. Visual browser verification was unavailable in this read-only environment.

## Blocking findings

- [medium] app/web/templates/bank/_transactions.html:14: “Saldo na mutatie” introduces unexplained bookkeeping terminology, with no corresponding entry in `app/domain/glossary.py`. → Lead with wording such as “Bedrag op je rekening na deze betaling”, and provide a centrally sourced glossary explainer for the bookkeeping term.

## Nice-to-have

- app/web/templates/bank/preview.html:69: Show the previously imported transaction alongside each “Mogelijk dubbel” row, or link to it. Users currently must leave the preview to compare descriptions before deciding whether to import.
- app/web/templates/bank/account_form.html:24: The hint promises an automatic name when left blank, but editing an existing account rejects a blank name. Adjust the hint for editing or apply the same fallback.

STATUS: DONE