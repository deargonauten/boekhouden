VERDICT: REWORK

## Summary
The flows generally use clear Dutch, glossary explanations and existing UI patterns. One payment-date mismatch needs fixing before release. Used the supplied test result; browser verification was blocked by a sandbox initialization error.

## Blocking findings
- [medium] app/web/templates/sales/edit.html:36: Payment defaults and the displayed due date do not update when the customer, invoice date or payment term changes (AC 19–20). For example, selecting a customer with a 14-day term still displays the initial 30-day hint and due date, while saving silently uses 14 days. The confirmation screen also omits the resulting dates, allowing an invoice to become immutable with a deadline the user never saw. → Update the suggested term, explanation and calculated due date as inputs change, preserve manually chosen dates, and show the effective payment deadline before finalization.

## Nice-to-have
- app/web/templates/sales/detail.html: Add the invoice email handoff described in spec section 2: a prefilled “Mail aan klant” link, copyable text and a reminder to attach the downloaded PDF. Currently those conveniences exist only for reminders.

STATUS: DONE