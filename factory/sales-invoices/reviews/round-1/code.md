VERDICT: REWORK

## Summary
Three correctness issues remain in issued PDFs, credit limits, and settlement after reversal. Reviewed against the supplied result of 2210 passing tests; no full-suite rerun.

## Blocking findings
- [P1] app/domain/sales/service.py:706: Every finalized invoice and credit note is rendered before `invoice.status` becomes `definitief`. `_document()` therefore sets `is_concept=True`, and the permanently stored PDF says “CONCEPT - nog niet definitief”. Downloads serve those stored bytes. → Render the issued document with `is_concept=False` while preserving transaction rollback. Add an integration assertion against the stored PDF, alongside the concept-preview check.

- [P2] app/domain/sales/service.py:644: Credit finalization checks cumulative quantities but never cumulative credited amounts. Independently rounded partial credits can exceed the original: one unit priced at €1.01 with NL_0 totals €1.01; two successive credits of 0.5 units each total €0.51 apiece. Both pass the quantity check, leaving an extra refundable cent after full settlement, contrary to AC 15. → Enforce the monetary limit across finalized credits as well as the quantity limit, with regression coverage for fractional quantities and VAT rounding.

- [P2] app/domain/sales/service.py:187: `_applied_maps()` always subtracts applications from the credit note, even when the original invoice has been reversed. Finalize an invoice for €121, fully credit it, then reverse the original entry through Boeken: both documents show zero open, while account 1300 retains a €121 credit balance. The remaining credit is also unavailable for bank reconciliation. → Release the credit note’s applied amount when its target invoice is reversed, and test that debtor totals and reconciliation agree with account 1300 after this sequence.

## Nice-to-have
None.

STATUS: DONE