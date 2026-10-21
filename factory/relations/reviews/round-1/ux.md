VERDICT: PASS
## Summary
Flows meet the user stories. Plain Dutch leads on every label, with the term and info icon next to it. Glossary entries exist for kvk, btw_nummer, iban, klant, leverancier and archiveren, and all are used by templates. Helper text matches the spec. Errors are listed together, in Dutch, and entered values are kept. The empty state explains what relations are and offers an action. Archived rows are muted and labelled. There is no delete route. Full suite passes (502 tests).
## Nice-to-have
- The list gives no feedback on archive/restore, because the redirect is a bare /relaties. A short notice ("Relatie X is gearchiveerd") would help, especially since an archived row disappears from the default list.
- When the soort filter combined with "toon gearchiveerd" is active, the archived-row label is only in the Status column. That is fine, but the badge could also appear next to the name on narrow screens.
- Form: the "Notities" field is a single-line input; a textarea suits free text better.
- Error list shows no per-field highlighting, so the user must map messages to fields. Messages do name the field, so this is acceptable.
- The archive button text "Relatie archiveren" is repeated on every row. That is OK, but it is verbose.
