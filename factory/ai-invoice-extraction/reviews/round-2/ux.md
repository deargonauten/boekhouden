VERDICT: PASS
## Summary
Round 1 had no blocking findings; delta only.
- The change fixes a real flow bug: saving or finishing review previously reset a creditnota to `invoice`. The hidden field keeps the kind, and `tests/test_extraction_web.py::test_review_keeps_document_kind` covers both Opslaan and Klaar met nakijken.
- No new visible text or terms, so no new glossary entries are needed. The existing creditnota notice (with info("creditnota")) is unchanged.
- An invalid kind yields a plain Dutch error that says what to do.
## Nice-to-have
- NULL kind edge case would show "'None' is geen geldig soort document"; default to `invoice` in the template.

STATUS: DONE
