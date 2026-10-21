VERDICT: PASS
## Summary
Read the routes, all five inbox templates, the glossary diff and the tests (tests/test_plain_language.py and tests/test_extraction_web.py: 45 passed). I did not run the app in a browser.

- **Flow:** it matches the user stories. The inbox has a per-row action and a batch button with a count. The review page shows the original file next to an editable form, with a "N velden om te controleren" summary, per-field Controleer/Onzeker badges with reasons, and Opslaan / Klaar met nakijken. Opnieuw uitlezen has a confirm prompt.
- **Busy state:** the body has `hx-boost`, so `hx-indicator` and `hx-disabled-elt` take effect. The button is disabled and "Bezig met uitlezen..." shows while a request runs.
- **Errors and empty states:**
  - A failed extraction, not logged in, a rate limit and "not read yet" all render plain-Dutch messages with a next step.
  - The batch run stops early and says how many documents are left.
  - A validation error keeps the user's input (422).
- **Plain language:** labels lead in plain Dutch ("Wat is er uitgegeven?", "Op welke rekening boeken?" with the Grootrekening term, "Hoeveel BTW?", "Van welke leverancier?"). Each term has an `info()` explainer. The review page has no accountant-only jargon without an explainer.
- **Glossary:** all 8 new keys are in `app/domain/glossary.py` (uitlezen, nakijken, btw_tarief, verlegd, creditnota, factuurdatum, vertrouwen, claude_abonnement). The explanations are short and in plain Dutch, and all are used in templates. `UNUSED_OK` is still empty.
- **Defaults:** the account and BTW code are preselected from the suggestion, and the supplier is shown as matched or new. The hint for an unknown account reads "Kies 4999 Nog te verdelen".

## Nice-to-have
- `PAGES` in tests/test_plain_language.py only gains `/inbox/1/nakijken` in its not-yet-read state. The spec (AC 31) also asked for the review page with extraction data and the detail page with an extraction error. The comment says these are covered in test_extraction_web.py. Please check that file asserts that every `info()` key renders there, or add those states to `PAGES`.
- The hint "Kies 4999 Nog te verdelen" is hard-coded. If account 4999 is missing from the user's schema the hint misleads. Consider showing it only when the account exists.
- After a 422, the per-line flags are matched by index to the submitted lines. If the user deleted a row before saving, the badges can end up on the wrong row. It is cosmetic and only on the error re-render.
- The "Verwijder regel" button is JS-only with no confirm. That is fine since nothing is saved until Opslaan.
- Several fields in the supplier section (adres, postcode, plaats, land, valuta) are bare labels with no explainer. This is acceptable because they are not bookkeeping terms.

STATUS: DONE
