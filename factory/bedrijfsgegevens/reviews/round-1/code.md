VERDICT: PASS
## Summary
Full suite on the integrated branch: 1122 passed. Acceptance criteria 1-18 checked against code and tests: single-row table with CHECK constraints and migration 0006, validation in domain only (all messages match the spec wording), all errors collected into one CompanyError, thin routes (303 to ?opgeslagen=1, 422 with typed values kept and rollback), frozen CompanyProfile with missing_for_invoice/address_lines/iban_display, require_company_for_invoice, public API in app.domain.company, SETTINGS_NAV group "Mijn bedrijf" first, glossary keys added and plain-language tests extended. Routes contain no business logic. Tests cover the spec's strategy (domain, service, schema, web).

Accepted deviations (reasonable): glossary term text for `bedrijfsgegevens` is "Mijn bedrijfsgegevens" with a never-matching detect pattern, and the relations form heading was renamed to avoid a bare-term clash; the settings page h1 is "Jouw bedrijfsgegevens". Small country-name map in profile.py.

## Nice-to-have
- profile.py `_COUNTRY_NAMES` is a 7-entry map; unknown countries fall back to the 2-letter code. Fine for now, revisit if foreign addresses matter.
- validation.py imports the private `_clean` from relations.validation; consider making it public.
- If `country` is invalid, the postal code is checked with the NL rule, so the user may see a postcode error next to the country error. Harmless.
- Country and email errors keep the relations error codes (INVALID_COUNTRY/INVALID_EMAIL) rather than company-specific ones; messages are plain Dutch so no user impact.

STATUS: DONE
