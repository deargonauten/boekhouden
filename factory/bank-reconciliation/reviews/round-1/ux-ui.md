VERDICT: REWORK

## Summary
The flow has clear Dutch headings, actionable errors, accessible field labels, and consistent shared components. One explanation gap blocks the explicit requirement to support users without bookkeeping knowledge.

Reviewed the diff and build reports; accepted the reported 1964 passing tests. Visual browser verification was unavailable because no app was listening on localhost:8000.

## Blocking findings
- [medium] app/web/templates/bank/reconcile_detail.html:58: “Creditnota” appears without plain Dutch wording or its glossary explanation, including in the booked view at line 134. Users must understand that this item reduces the payment rather than adding to it, but every amount is displayed as positive. → Show a plain Dutch label alongside the term, expose `info("creditnota")`, and explain how selecting it affects the amount to distribute using centrally maintained glossary text.

## Nice-to-have
- app/web/templates/bank/reconcile_detail.html:73: Adapt “Wat is dit voor uitgave?” for incoming transactions so refunds and other receipts have an appropriate heading.
- app/web/templates/bank/rules.html:26: Display the readable VAT name instead of an internal code such as `NL_21`, with the glossary explanation available.

STATUS: DONE