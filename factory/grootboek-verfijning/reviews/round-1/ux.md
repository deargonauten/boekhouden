VERDICT: PASS
## Summary
Reviewed templates, JS and routes in the diff and ran the full suite (1289 passed). Btw-codes page, Grootboek columns/modal and the suggestion flow (manual boeking + inbox review) meet the acceptance criteria. Plain-Dutch check holds: the lead text is in plain Dutch, every new term (rubriek, standaard btw-tarief, selecteerbaar bij, voorbelasting, KOR) uses `info()` from the central glossary, an empty rubriek reads "Telt niet mee in de aangifte", locked system accounts show a Dutch explanation, defaults are prefilled (NL_21 for expense, contexts from `default_contexts`, rubriek suggestions per percentage). Errors render via `error_box` with the spec's Dutch messages.

## Nice-to-have
- Inbox review: the btw select is not marked `data-touched` when the server prefilled it from the invoice extraction (only the manual boeking form does this). Changing the account on a line can therefore silently overwrite a btw-code that was read from the invoice (e.g. 9% becomes the account's 21%). Consider setting `data-touched="1"` when `line.vat_code` is set and was extracted, in `_review_line.html`.
- Grootboek rows have two separate "Opslaan" buttons per row (btw and selecteerbaar); a changed checkbox without clicking Opslaan is lost. Acceptable per spec, but a hint or auto-submit on change would be friendlier.
- On the edit modal of Btw-codes, the code (e.g. NL_21) is only shown in a hint under Naam; fine.
