VERDICT: APPROVE
## Reasoning
Process followed: spec approved, Part A (domain/schema/migration/glossary) and Part B (web/nav/templates) built in separate worktrees with reports, integrated on factory/bedrijfsgegevens, one review round (security, ux, ui, code) all PASS with only nice-to-haves. Full suite re-run by me: 1122 passed (1 `live` smoke test deselected by project config). Spot-checked diff: migration 0006, models, domain package, thin routes, nav group "Mijn bedrijf" first, glossary keys, plain-language tests extended. Deviations (glossary term text "Mijn bedrijfsgegevens", relations heading renamed, small country-name map) are reasonable and documented.

## Acceptance criteria check
1. Screen, prefilled, defaults, lead sentence: met
2. Nav group "Mijn bedrijf" first, /instellingen redirect unchanged: met
3. Fields and plain-Dutch labels: met
4. Save/303 flash/422 with typed values and combined errors: met
5. Completeness banner: met
6. Single row enforced by DB CHECK id=1: met
7-14. Validation in domain with spec messages, NULL for empty, combined CompanyError: met (per code review and tests)
15-18. Read API (CompanyProfile, missing_for_invoice, require_company_for_invoice, public __init__): met
Plain-language/glossary requirement (bedrijfsgegevens, btw_id, handelsnaam, rechtsvorm; plain-language tests over empty/filled/error states): met

## Outstanding issues
No REWORK findings. Nice-to-haves only: no length cap on address/city/phone; no CSRF (app-wide, localhost); country field lacks a hint and layout is slightly untidy; no per-field aria-invalid; flash and "compleet" notice stack after save; `_clean` imported privately from relations.validation; country/email errors keep relations error codes. Not blocking.

## What the human should look at (if HUMAN_REVIEW)
Not applicable. Optional: glance at the page visually (UI reviewers did not run the app) and at the wording "Mijn bedrijfsgegevens" in the glossary.

STATUS: DONE
