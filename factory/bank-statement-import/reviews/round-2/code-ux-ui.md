VERDICT: PASS

## Summary

Both previous blocking findings are resolved in the last two commits.

- CAMT amounts now derive their sign solely from `CdtDbtInd`. The corrected fixture and regression tests cover credit and debit reversals, including balance reconciliation.
- The transactions table now shows “Saldo erna” with an explainer sourced from `app/domain/glossary.py`.
- The account-name hint correctly distinguishes creating and editing.

No blocking code or UX/UI regressions found in the delta. Used the reported result of 1665 passed, 1 deselected; did not rerun the suite. Visual browser verification was not performed.

## Nice-to-have

None added.

STATUS: DONE