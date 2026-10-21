VERDICT: PASS
## Summary
Rendered all ledger screens via TestClient and ran the full suite (341 passed). Plain Dutch leads with the term in brackets and an info icon on every screen I checked (boekjaren, dagboeken, grootboek, boeken list, nieuwe boeking, sidebar). Defaults work: MEM is preselected, "Geen btw" is the first VAT option, the year and account code are suggested. The unbalanced error reads "Debet en credit zijn niet gelijk: er ontbreekt € 12,10 aan de creditkant. Pas een bedrag aan..." and the table footer repeats it. Lock/close confirmations are plain and say they cannot be undone. Wording is understandable for a non-accountant.

## Nice-to-have
- Unbalanced message ends "... of voeg een regel toe. (debet € 100,00, credit € 87,90)." The bracket after a full stop reads oddly; put the totals inside the first sentence.
- Nieuwe boeking VAT select shows "Geen btw" twice (empty option and the GEEN code "Geen btw (GEEN)"), and raw codes like (EU_DIENSTEN) appear. Sorting is alphabetical, so rare EU/export options come before BTW 21% and 9%. Hide the GEEN duplicate and order common rates first.
- `.info-tip` is anchored at `left:0` of `.content`, so for icons far to the right the tooltip appears at the left edge of the row, away from the icon. Readable but slightly disconnected; anchor to `.info` with `position:relative` plus overflow handling on narrow screens.
- "Bedrag links / Bedrag rechts" for debet/credit is a rough plain phrase; consider "Ontvangen / Betaald"-style wording only if it can be context-correct, otherwise keep as is.
- Nieuwe boeking when no boekjaar exists gives no up-front hint; the user only learns on submit (the error is plain, so not blocking).
- Account type groups on nieuwe boeking list liability 3xxx before equity 2xxx (order follows type, not code); cosmetic.
