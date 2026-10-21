VERDICT: PASS
## Summary
Read the template, routes, glossary entries, nav and settings header; full suite is green (1122 passed). The flow matches the spec. Plain Dutch leads, lead sentence and completeness notice are present, defaults NL/eenmanszaak are suggested, and hints sit under kvk/btw-id/iban. Glossary has bedrijfsgegevens, btw_id, handelsnaam and rechtsvorm, and the template uses info()/term_label for them plus kvk/iban. Errors are listed together in error_box and typed values are kept (422). The IBAN is prefilled grouped. The relations form heading was renamed so the "Bedrijfsgegevens" wording does not clash.
## Nice-to-have
- Invalid fields are not marked individually (no aria-invalid or per-field message); the error_box lists them, which is enough for a single-user app.
- The required marker span for legal_name is empty and aria-hidden, so the visual asterisk depends on CSS; the `required` attribute covers accessibility.
- Country field is a free 2-letter input; a user may not know what to type for non-NL, but NL is the default.
STATUS: DONE
