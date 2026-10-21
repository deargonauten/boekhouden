VERDICT: PASS
## Summary
UX lens, round 1. I ran the app on a scratch database (empty, then with one boekjaar and one relatie) and read the rendered HTML for /boeken (with ?q and ?page=0), /boeken/nieuw, /relaties (empty, no-match, with row, validation error), /inbox, /instellingen/{grootboek,dagboeken,boekjaren}, /bank and a 404. I also read the templates and CSS. `uv run pytest` passes (994 passed), including the plain-language tests. I did not check visuals in a browser at 375/768/1280px or in dark mode; that belongs to the ui lens.

What works:
- Every page has the same structure: breadcrumb, h1, a plain-Dutch lead, one primary button, then a card with tabs, search and table, with a pager below. Statuses are pills with text (Actief, Open, Klant). Search and tab links keep the other parameters in the URL.
- Empty states are plain Dutch and say what to do. "Je hebt nog geen boekingen / relaties", "Nog niets om te verwerken" and "Er is nog geen boekjaar" each have a call to action. The no-match states ("Geen boekingen gevonden", "Geen relaties gevonden") offer "Wis filters". Placeholder and 404 pages use `empty_state` and link back to Inbox.
- Terms follow "plain Dutch first, term in parentheses, info icon". Examples: "In welk dagboek? (Dagboek)", "Maand (Periode)", "Op slot zetten (Vergrendelen)". Tab labels, table headers (KvK, IBAN, Btw-nummer), status tabs in the inbox and the archive switch all have `info()` with glossary text.
- Errors are readable. The relatie form shows `role="alert"` with "Vul de naam van de relatie in." Destructive actions (afsluiten, vergrendelen) keep `hx-confirm` with plain explanations. Icon-only actions have `aria-label` and a plain-Dutch `title` (acceptance criterion 15).
- The entry form has the "Algemeen" and "Regels" cards, a suggested default dagboek (Memoriaal), the date prefilled, and plain-Dutch placeholders.

## Nice-to-have
- `ledger/fiscal_years.html`: the heading reads "Boekjaren (Boekjaar)", which is redundant. The page header already says "Instellingen". Use "Je boekjaren".
- The periodes table shows "1", "2" ... for the maand. Month names ("januari") would be clearer. All 12 vergrendel buttons share the aria-label "Periode vergrendelen" (the `title` is identical too). Add the month to the label.
- /relaties: empty KvK, Btw and IBAN cells are blank. A muted "-" reads better. The "Zoeken" button there is secondary, while /boeken has only a visually-hidden submit (Enter works). Make the pattern consistent.
- /boeken: the dagboek tabs read "VK Verkoopboek / BANK Bank". The code prefix is noisy for a non-accountant; the name alone would do, with the code kept in the title.
- In the inbox, the info icons sit outside the tab link. That is fine, but check the tap target on mobile.
- Relatie archiveren has no confirm. It is reversible (Herstellen), so this is acceptable.
- Port 8000 may be occupied by other tools. This does not affect the app.

STATUS: DONE
