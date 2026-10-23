VERDICT: REWORK
## Summary
The main reporting and snapshot flow is well structured, but three correctness gaps need fixing. Reviewed against the spec and supplied test result (2476 passed, 1 deselected); no full suite rerun.

## Blocking findings
- [high] app/domain/vat/filing.py:235: Filing checks overlapping dates but never rejects a different return kind already filed in the same year. After filing Q1, filing April as a month succeeds and irreversibly creates mixed frequencies. The overview then selects one kind and hides the other return. → Reject any filing whose kind differs from an existing return in that year, with `VAT_FREQUENCY_CONFLICT`; add a regression test for non-overlapping periods.
- [medium] app/domain/vat/report.py:290: W3 combines all regular sales rubrieken before comparing expected and actual VAT. A booking with €100 at 21% and €100 at 9%, but €9 on 3100 and €21 on 3110, receives no warning although both declaration boxes are wrong. → Compare expected and booked amounts per entry/rubriek, as required by acceptance criterion 5, and test compensating discrepancies.
- [high] app/domain/vat/export.py:181: PDF and ICP CSV exports omit `snapshot.icp_unassigned` entirely. When all EU sales lack a customer, the PDF even says “Geen EU-verkopen in deze periode” despite a nonzero 3b amount. Filing permits these warnings, so the omission can persist in a frozen return. → Include unresolved sales and their amounts in the PDF, explicitly flag incomplete ICP exports, and prevent the CSV from silently presenting an incomplete total as complete. Cover both entirely and partially unassigned sales.

## Nice-to-have
None.

STATUS: DONE