Status: APPROVED

# Spec: grootboek-verfijning

Backlog item: standaard btw-code per rekening als suggestie, "selecteerbaar bij" voor kortere keuzelijsten, btw-codes beheren met rubriek-koppeling (features 32, 33, 20 in `factory/moneymonk-style-restyle/feature-candidates.md`, besluit: opnemen).

## 1. Goal and context

Today the ledger already stores `account.default_vat_code` (seeded: expenses 21%, 4400/4800/4900/4910/4960 "Geen btw", revenue per rate) and `vat_code(code, name, rate_bp, is_active)`, but:
- nothing uses `default_vat_code` (no UI, no suggestion);
- every account dropdown lists every active postable account (inbox review lists all expense accounts; manual boeking lists everything);
- `vat_code` has no link to a BTW-aangifte rubriek, and there is no screen to see or manage the codes.

This feature (a) uses the account's default btw-code as a pre-filled suggestion, (b) lets the user decide per account where it shows up (inkoop / verkoop / bank) so pick-lists get short, (c) adds a "Btw-codes" settings page where codes and their aangifte-rubriek are managed. (c) is the foundation for the later BTW-aangifte feature (14): rubriek is derived from the vat code on journal lines.

Existing conventions to follow: Alembic migration (latest is `0006_company_profile`; migrations must not import `app.models`, they may import `app.seed`), SQLAlchemy models in `app/models/ledger.py`, business logic in `app/domain/` (routes only parse and render), `LedgerError(code, message)` with Dutch messages, glossary in `app/domain/glossary.py`, `info()`/`term_label()` macros, `error_box`, settings pages extending `base_settings.html` with `settings_header` from `ledger/_settings_nav.html`.

## 2. Non-goals

- No BTW-aangifte screen, no rubriek totals, no ICP (features 14/15/19). Only the mapping data.
- No supplier-to-account learning (feature 41), no bank import / direct-book screens (6, 9) and no sales-invoice screen; they will call the domain helpers created here.
- No per-vat-code deletion (deactivate only), no editing of a code's percentage once the code is used on a journal line.
- No change to how a posted entry is stored; `journal_line.vat_code` stays as is. No automatic vat-amount line generation.
- No KOR code is seeded (see decisions); the user can add one.
- No rubriek mapping per account (it is per btw-code only).
- The manual boeking form (`/boeken/nieuw`) keeps listing all active postable accounts (the escape hatch for anything unusual); it only gains the btw suggestion.

## 3. User stories

1. As a user booking an inkoopfactuur (inbox review), when I choose "Telefoon en internet" the btw-tarief is filled in as 21% without me choosing it, and I can still change it.
2. As a user, the rekening list in the inbox review only shows accounts meant for inkoop, so I don't scroll through Debiteuren or Bank.
3. As a user, on Instellingen > Grootboek I can switch per rekening whether it shows up bij inkoop, verkoop and bank, and pick the standaard btw-tarief of the rekening.
4. As a user, on Instellingen > Btw-codes I see all btw-codes with percentage and in which rubriek of de btw-aangifte they land (verkoop and inkoop side), can add a code (e.g. KOR, or 0% variant), rename it, change its rubriek, and switch it off.
5. As a user without bookkeeping knowledge, every term here has a short explanation and the defaults are already right, so I only confirm.

## 4. Acceptance criteria

### Data and migration
1. Migration `0007_grootboek_verfijning` (down_revision `0006_company_profile`) adds:
   - `vat_code.sales_rubriek` String null, `vat_code.purchase_rubriek` String null, `vat_code.is_system` Boolean not null server_default 0;
   - `account.selectable_purchase`, `account.selectable_sales`, `account.selectable_bank` Boolean not null server_default 0.
   Models in `app/models/ledger.py` match exactly (`alembic check` shows no drift; `tests/test_migrations.py` expects head `0007_grootboek_verfijning`; downgrade to base works).
2. Migration backfills existing rows (idempotent UPDATEs, plain data from a new `app/seed/vat_rubrieken.py` and `app/seed/rgs_accounts.py`; no model imports):
   - The 8 seeded codes get `is_system = 1` and rubrieken:

     | code | sales_rubriek | purchase_rubriek |
     |---|---|---|
     | GEEN | null | null |
     | NL_21 | 1a | 5b |
     | NL_9 | 1b | 5b |
     | NL_0 | 1e | null |
     | VERLEGD | 1e | 2a |
     | EU_GOEDEREN | 3b | 4b |
     | EU_DIENSTEN | 3b | 4b |
     | EXPORT | 3a | 4a |

   - Account contexts via one pure function `default_contexts(type, is_system, code) -> (purchase, sales, bank)` in `app/seed/rgs_accounts.py`, also used by `add_account`. Rules: expense and not system: purchase+bank; revenue: sales+bank; asset non-system: purchase+bank for 0100/0110/0120 (bedrijfsmiddelen), bank only for the other non-system assets; equity 2010/2020/2030: bank; liability non-system: bank; every other system account (Kas, Bank, Debiteuren, Crediteuren, btw-rekeningen, 4950, 4999, 2000, 2900, 2910, 0190, 1230): none. Revenue 8000 (system) counts as revenue: sales+bank (the "system" exclusion only applies to the explicit list above: 0190, 1100, 1210, 1230, 1300, 1400, 1410, 2000, 2900, 2910, 3000, 3100-3150, 4950, 4999).
3. `Account.default_vat_code` remains the single "standaard btw-code" field (no new column). Seed values are left unchanged.

### Btw-codes (domain, new package `app/domain/vat/`)
4. Rubriek catalogue (`app/domain/vat/rubrieken.py`, pure): sales side `1a 1b 1c 1d 1e 3a 3b 3c`, purchase side `2a 4a 4b 5b`, each with a short plain-Dutch label (e.g. 1a "Omzet met 21% btw", 1b "Omzet met 9% btw", 1c "Omzet met een ander btw-tarief", 1d "Privégebruik", 1e "Omzet met 0% of waarbij de klant de btw afrekent", 2a "Btw verlegd naar jou", 3a "Verkoop buiten de EU", 3b "Verkoop binnen de EU", 3c "Installatie en afstandsverkopen binnen de EU", 4a "Inkoop van buiten de EU", 4b "Inkoop uit de EU", 5b "Voorbelasting (btw die je terugkrijgt)"). Constant `ALSO_INPUT_VAT = {"2a","4a","4b"}`: these purchase rubrieken also create voorbelasting in 5b (documented for feature 14; no logic here). Function `suggest_rubrieken(rate_bp) -> (sales, purchase)`: 2100 -> (1a, 5b); 900 -> (1b, 5b); 0 -> (1e, None); any other rate -> (1c, 5b).
5. `app/domain/vat/service.py` (DB), re-exported from `app/domain/vat/__init__.py`; `ledger.list_vat_codes` stays and keeps working:
   - `add_vat_code(session, *, code, name, rate_percent_text|rate_bp, sales_rubriek, purchase_rubriek)`: code 2-12 chars `[A-Z0-9_]` (input upper-cased); name required; rate 0-99,99% parsed from Dutch decimal text ("21", "21,0", "6,5") to basis points with integers only (no float); rubrieken must be in the catalogue for their side (sales value on sales side, etc.) or empty; duplicate code rejected. New codes are `is_system = 0`, active.
   - `update_vat_code(session, code, *, name, sales_rubriek, purchase_rubriek)`: system codes: name AND rubriek editable, code and rate never. Rate of any code is never editable after creation (no UI field). Rubriek change is refused when the code appears on a journal line whose entry is in a locked period (see messages).
   - `set_vat_code_active(session, code, active)`: deactivating a code that is `default_vat_code` of any active account is refused (message below). `GEEN` can never be deactivated.
   - `list_vat_codes_with_usage(session)`: rows with code, name, rate_bp, rubrieken, is_active, is_system, `used_count` (journal lines), `default_for` (account codes). Ordering: system codes in seed order (GEEN, NL_21, NL_9, NL_0, VERLEGD, EU_GOEDEREN, EU_DIENSTEN, EXPORT), then custom by code.
   - `rubriek_for(session, vat_code, direction)` where direction is `"sales"|"purchase"`: returns the rubriek or None (the hook feature 14 will use).
6. Exact error messages (Dutch, via `LedgerError`; stable codes in brackets):
   - `[INVALID_VAT_CODE]` bad code: "Een btw-code bestaat uit 2 tot 12 hoofdletters, cijfers of liggende streepjes, bijvoorbeeld KOR of NL_5."
   - `[DUPLICATE_CODE]`: "De btw-code {code} bestaat al. Kies een andere code."
   - `[INVALID_VAT_CODE]` name: "Geef de btw-code een naam, bijvoorbeeld 'BTW 6%'."
   - `[INVALID_VAT_RATE]`: "Vul een percentage tussen 0 en 99,99 in, bijvoorbeeld 21 of 6,5."
   - `[INVALID_RUBRIEK]`: "Rubriek {x} past hier niet. Kies een rubriek uit de lijst of laat het veld leeg."
   - `[VAT_CODE_IN_LOCKED_PERIOD]`: "Deze btw-code is al gebruikt in een vergrendelde periode, dus de rubriek kun je niet meer wijzigen. Maak een nieuwe btw-code aan voor het nieuwe geval."
   - `[VAT_CODE_IS_DEFAULT]`: "Je kunt {name} niet uitzetten: het is nog het standaard btw-tarief van rekening {code} {naam}. Kies eerst bij die rekening een ander tarief." (lists up to 3 accounts, then "en nog N andere")
   - `[VAT_CODE_SYSTEM]` (GEEN deactivate): "'Geen btw' is nodig voor boekingen zonder btw en kan niet worden uitgezet."

### Grootboek: standaard btw-code and selecteerbaar bij
7. `ledger.set_account_vat_default(session, account_id, vat_code|None)`: code must exist and be active else `INVALID_VAT_CODE` (existing message); None clears. Allowed on system accounts (it only changes a suggestion). Not allowed on non-postable (kopregel) accounts: "Een kopregel heeft geen btw-tarief; kies een rekening eronder."
8. `ledger.set_account_contexts(session, account_id, *, purchase, sales, bank)` (three bools). Refused on system accounts that have all-false defaults and are in the explicit exclusion list of criterion 2 with: "Dit is een standaardrekening die het programma zelf gebruikt; hij verschijnt niet in keuzelijsten en dat kun je niet aanpassen." Allowed for every other account, including 8000.
9. `ledger.list_accounts_for(session, context)` where context in `"purchase"|"sales"|"bank"`: active, postable accounts with the matching flag, ordered by code. Unknown context raises `ValueError` (developer error). `ledger.suggest_vat_code(session, account_id) -> str | None` returns the account's `default_vat_code` only if that code is active, else None. Both re-exported from `app/domain/ledger/__init__.py`. `add_account` gets optional `default_vat_code` (already present), plus the three context flags defaulting to `default_contexts(...)`.
10. Changing defaults/flags never alters existing journal lines and is allowed in any period (they are UI hints, not bookings).

### Screens
11. **Instellingen > Btw-codes** (`GET /instellingen/btw-codes`, nav item "Btw-codes" in the Boekhouding group of `SETTINGS_NAV`, between Grootboek and Dagboeken, term key `btw_code`). Plain-Dutch lead: "Een btw-code is het btw-tarief dat je bij een bedrag kiest, bijvoorbeeld 21% of 'btw verlegd'. Bij elke code staat in welk vakje van je btw-aangifte het bedrag later terechtkomt." Table columns: Naam, Percentage, "Vakje bij verkoop" (rubriek + plain label, info icon term `rubriek`), "Vakje bij inkoop", Status (Actief/Inactief, "Standaard" pill for system), Acties (bewerken, uitzetten/aanzetten). Empty rubriek shows "Telt niet mee in de aangifte". Edit and add via the existing `modal()` pattern with `hx-boost="false"` forms (like accounts): fields Code (add only), Naam, Percentage (add only; shown read-only on edit with hint "Het percentage kun je niet meer wijzigen. Maak een nieuwe code aan als het tarief verandert."), Vakje bij verkoop and Vakje bij inkoop as selects built from the catalogue with labels ("1a - Omzet met 21% btw"). On the add form, changing the percentage pre-selects the suggested rubrieken (`suggest_rubrieken`) via a small `hx-get` fragment or server round-trip; default when opened: 21% suggestions. Errors via `error_box`, status 400 like the existing ledger pages (routes list reuse `_status_for`-style mapping; new error codes map to 400, `VAT_CODE_IN_LOCKED_PERIOD`/`VAT_CODE_IS_DEFAULT` to 409).
    - POST `/instellingen/btw-codes` (add), POST `/instellingen/btw-codes/{code}` (update), POST `/instellingen/btw-codes/{code}/actief` (toggle). 303 redirects after success (same as the accounts routes).
12. **Instellingen > Grootboek** (`/instellingen/grootboek`): table gets two columns, "Btw-tarief (standaard)" (a `<select>` of active codes plus "Geen suggestie", submitted per row via small inline forms POST `/instellingen/grootboek/{id}/btw`) and "Selecteerbaar bij" (three checkboxes Inkoop / Verkoop / Bank in one inline form POST `/instellingen/grootboek/{id}/selecteerbaar`). System accounts in the exclusion list show the columns read-only with the explanation as title. Only rendered for postable accounts. The add-account modal gets the same "Standaard btw-tarief" select (preselected from type: expense -> NL_21, revenue -> NL_21 for 8xxx? No: preselect none for revenue; expense NL_21; others none) and the three checkboxes preselected by `default_contexts`. Existing `Soort rekening` change does not auto-update them (documented hint: "Dit zijn voorstellen; je kunt ze straks aanpassen.").
13. **Suggestion behaviour (manual boeking `/boeken/nieuw`, `_line_row.html`)**: each account `<option>` carries `data-vat="{default_vat_code or ''}"` (only active codes). A small script `app/web/static/js/vat-suggest.js` (new file, loaded from the form via `{% block head %}`/script tag) sets the btw `<select>` of the same row to `data-vat` when the account changes AND the user has not touched that btw select yet (track with `data-touched`); an empty default selects "Geen btw". Rows added via HTMX (`/boeken/nieuw/regel`) work too (event delegation on `#line-rows`). Server-side re-render after an error keeps submitted values (no overwrite).
14. **Inbox review (`inbox/review.html`, `_review_line.html`)**: the rekening list is `list_accounts_for(session, "purchase")`, with any account already chosen on a line (selected) always included even if not selectable, selected ones first (current behaviour kept). Option carries `data-vat` and the same script prefills the btw-tarief when the user picks an account and has not touched the btw select. Server side, when the extraction gave an account but no resolvable vat code (`resolve_vat_code` returns None), the line is pre-filled with `suggest_vat_code` of that account; it counts as a suggestion (not marked as inferred-from-amounts). The existing VAT-amount and flag logic stays; if the vat amount on the invoice contradicts the suggested code the existing flags apply unchanged.
15. All new/changed screens contain no raw exception text; every error is the Dutch message above rendered in an `error_box`.

### Plain-language requirement (CLAUDE.md)
16. New glossary entries in `app/domain/glossary.py` (explanation max 220 chars, `plain != term`, keys `[a-z_]+`):
    - `rubriek` ("Rubriek", "Vakje in de btw-aangifte"): "Een genummerd vakje op het btw-formulier, zoals 1a of 5b. Het programma zet elk bedrag in het juiste vakje op basis van de btw-code." (detect `\brubrieken?\b`)
    - `standaard_btw` ("Standaard btw-tarief", "Tarief dat vooraf wordt ingevuld"): "Het btw-tarief dat het programma voorstelt als je deze rekening kiest. Je kunt het bij elke boeking nog aanpassen."
    - `selecteerbaar_bij` ("Selecteerbaar bij", "Waar de rekening in de lijst staat"): "Bepaalt in welke keuzelijsten de rekening verschijnt: bij inkoop, verkoop of bank. Zo houd je de lijst kort en kies je sneller de goede rekening."
    - `voorbelasting` ("Voorbelasting", "Btw die je terugkrijgt"): "De btw op je inkopen en kosten. Die mag je aftrekken van de btw die je zelf moet afdragen." (detect `\bvoorbelasting\b`)
    - `kor` ("KOR", "Kleineondernemersregeling"): "Met de KOR reken je geen btw aan en trek je ook geen btw af, zolang je omzet onder de grens blijft. Je doet dan geen btw-aangifte."
    - `icp` is NOT added (ICP is out of scope; the EU rubriek labels avoid the term).
    Existing `btw_code` explanation is kept. The words "verlegd" and "btw-tarief" use existing `verlegd`/`btw_tarief` entries via `info()` on the Btw-codes page. Every column header with a term uses `term_label`/`info`. `tests/domain/test_glossary.py` REQUIRED list gets the five new keys; `tests/test_plain_language.py` PAGES gets `/instellingen/btw-codes` and the updated `/instellingen/grootboek`.
17. Suggested defaults list: standaard btw per rekening (seed: kosten 21%, bank/verzekering/afschrijving "Geen btw"), rubrieken per btw-code (criterion 2 table, `suggest_rubrieken` for new codes), selecteerbaar bij per rekeningtype (criterion 2), rekening list in inbox limited to inkoop.
18. Plain-Dutch labels: the visible words are "Btw-tarief", "Vakje in de btw-aangifte (rubriek)", "Selecteerbaar bij" with the info icon; code identifiers like `NL_21` are shown only in small grey text after the plain name, as the existing selects already do.

## 5. Technical approach

### Data model (all integers, no floats)
`vat_code`: `code` PK (string, existing), `name`, `rate_bp` int (basis points; 2100 = 21%), `is_active`, new `sales_rubriek`, `purchase_rubriek`, `is_system`. `account`: existing `default_vat_code` FK, new `selectable_purchase|sales|bank`. Rubriek values are plain strings validated in the domain against the catalogue, not a DB enum (the catalogue may grow when feature 14 adds rubrieken like 5a/5g).

Rate parsing: `parse_rate_bp("6,5") == 650` using `Decimal` on the Dutch text, quantized to 2 decimals, converted to int bp; reject exponent notation, negatives, > 99,99.

### Flows
- Add code: route parses form -> `vat.add_vat_code` -> redirect; on `LedgerError` re-render page with open modal and entered values (same pattern as `_accounts_page(add_error=True)`).
- Locked-period check for rubriek change: any `journal_line.vat_code = code` joined to `journal_entry.period_id` -> `period.status = 'locked'`.
- Suggestion: pure lookup `account.default_vat_code` filtered by active; JS only copies the data attribute, never calls the server.
- Inbox: `_ordered_accounts` in `app/web/extraction_routes.py` switches from `Account.type == "expense"` to `ledger.list_accounts_for(session, "purchase")` plus selected-in-use accounts (look up by code when not in the list). The extraction domain's own `resolve_account_code` (which still demands `type == "expense"`) is left alone except for the vat fallback below (note: asset purchases like 0110 remain pickable by hand on the review page but are not auto-suggested by the AI; out of scope).

### Error handling
All new errors are `LedgerError` with codes from criterion 6 added to `app/domain/errors.py` (constants only) and mapped to HTTP status in a small dict in the owning route module.

### Reuse
`app/domain/ledger/service._check_vat_codes` untouched. Seeds in `app/seed/vat_rubrieken.py` (`SEED_VAT_RUBRIEKEN: dict[str, tuple[str|None, str|None]]`, `SEED_VAT_ORDER`) imported by migration 0007 only.

## 6. Work breakdown (disjoint file ownership)

Order: Part 1 first (small, schema contract), then Parts 2 and 3 in parallel, then 4, 5 and 6 in parallel; Part 7 any time. Every part writes tests first for money/VAT logic (tdd skill).

**Part 1 - Schema, seeds, migration**
Owns: `app/models/ledger.py`, `app/seed/rgs_accounts.py` (add `default_contexts`; do not alter existing tuples), `app/seed/vat_rubrieken.py` (new), `migrations/versions/0007_grootboek_verfijning.py` (new), `app/domain/errors.py` (new code constants), `tests/test_migrations.py`, `tests/test_ledger_schema.py`, new `tests/test_grootboek_migration.py` (backfill table, `default_contexts` rules, upgrade/downgrade, `alembic check`).
Depends on: nothing. Integration contract: column names in criterion 1.

**Part 2 - Btw-code domain**
Owns: `app/domain/vat/` (new: `__init__.py`, `rubrieken.py`, `service.py`, `rates.py` for `parse_rate_bp`), `tests/vat/` (new).
Depends on: Part 1 (columns, error constants).

**Part 3 - Ledger domain additions**
Owns: `app/domain/ledger/service.py`, `app/domain/ledger/suggestions.py`, `app/domain/ledger/__init__.py`, `tests/ledger/test_account_contexts.py` (new), `tests/ledger/test_accounts_journals.py` (adjust for new `add_account` params).
Depends on: Part 1.

**Part 4 - Btw-codes settings page**
Owns: `app/web/vat_routes.py` (new), `app/web/templates/vat/codes.html` (new), `app/web/routes.py` (include router), `app/web/navigation.py` (new settings item), `tests/test_vat_codes_web.py` (new), `tests/test_help_page.py` (settings-nav expectations).
Depends on: Part 2. Integration point: `routes.py` and `navigation.py` are touched only by this part.

**Part 5 - Grootboek page and manual boeking suggestion**
Owns: `app/web/ledger_routes.py`, `app/web/templates/ledger/accounts.html`, `app/web/templates/ledger/_line_row.html`, `app/web/templates/ledger/entry_form.html`, `app/web/static/js/vat-suggest.js` (new, also used by Part 6 via a `<script src>`), `app/web/static/css/ledger.css` (only new classes), `tests/test_ledger_web.py`, new `tests/test_grootboek_web.py`.
Depends on: Part 3 (and the JS file contract: option attribute `data-vat`, select attribute `data-vat-target` on the account select with the CSS selector of the row's btw select is NOT used; the script finds the btw select as `tr select[name$="vat"], tr select[name$="vat_code"]`).

**Part 6 - Inbox review integration**
Owns: `app/web/extraction_routes.py`, `app/web/templates/inbox/review.html`, `app/web/templates/inbox/_review_line.html`, `app/domain/extraction/service.py` (vat fallback in `_line_rows` only), `app/domain/extraction/suggestions.py` (new `resolve_vat_code_for_account`), `tests/extraction/test_service.py`, `tests/test_extraction_web.py`, `tests/test_inbox_web.py` (if affected), new `tests/extraction/test_vat_default.py`.
Depends on: Part 3 and the JS file from Part 5 (agree on the path `/static/js/vat-suggest.js`; Part 6 only references it).

**Part 7 - Glossary**
Owns: `app/domain/glossary.py`, `tests/domain/test_glossary.py`, `tests/test_plain_language.py` (PAGES additions; `UNUSED_OK` must stay empty, so each new key must be used: `rubriek`/`voorbelasting`/`kor` appear on the Btw-codes page via Part 4 templates, `standaard_btw`/`selecteerbaar_bij` on the Grootboek page via Part 5; if a key is unused the test fails, so Parts 4/5 must use them).
Depends on: nothing to write; the plain-language page tests pass only after Parts 4 and 5 are merged (final integration check).

Integration point summary: columns (Part 1) -> domain (2, 3) -> pages (4, 5, 6); shared `vat-suggest.js` written by 5, referenced by 6; `routes.py`/`navigation.py` only by 4; glossary only by 7.

## 7. Test strategy

- Part 1: migration upgrade/downgrade/check; backfill: every seeded account has the expected flags (parametrised table for at least 4000, 4210, 4400, 8000, 8010, 1210, 1300, 0110, 2010, 3200, 3100, 4950); system codes have the rubriek table; `default_contexts` unit tests.
- Part 2: `parse_rate_bp` ("21"->2100, "6,5"->650, "0"->0, "21,999" rejected, "-1", "abc", "1e2"); add/update/deactivate rules and every error message text exactly; rubriek locked-period rule (create entry via `post_entry`, lock period); `rubriek_for` for each seeded code and both directions; usage counts; `suggest_rubrieken`.
- Part 3: `list_accounts_for` per context (excludes inactive, kopregel, wrong flag); `suggest_vat_code` returns None for inactive/unknown default; `set_account_*` rules incl. system accounts; `add_account` default flags per type.
- Parts 4, 5, 6 (web, TestClient with real migrated DB like existing `tests/test_ledger_web.py`): page renders all codes with rubriek labels; add/update/toggle via POST incl. error responses with Dutch text and kept form values; grootboek table has the new columns and POSTs persist; `/boeken/nieuw` HTML contains `data-vat` on options; inbox review lists only purchase-selectable accounts plus selected ones; vat fallback pre-fills 21% for 4210 when the extraction has an account but no vat code, and never overrides an inferred or given code.
- Plain language: `tests/test_plain_language.py` over the two settings pages (every glossary term has an icon, no bare terms); glossary entry validity tests.
- JS: not unit-tested; manual check listed for the reviewer (pick account -> btw changes; touch btw -> stays). The `data-vat` attribute and script tag presence are asserted server-side.
- Full `pytest` passes; money stays integer cents (no float anywhere new).

## 8. Risks and decisions made

- **Rubriek is per btw-code, with separate sales and purchase side.** One code behaves differently on each side (NL_21 is 1a on a sale, 5b voorbelasting on a purchase; verlegd is 1e as seller, 2a as buyer). A single rubriek column would be wrong. `ALSO_INPUT_VAT` documents that 2a/4a/4b also yield 5b so feature 14 does not need to re-derive it.
- **Rubriek changes are locked once the code was used in a locked period.** Rationale: the aangifte is derived from line codes (CLAUDE.md), and a closed period must not change; the user makes a new code instead. Open periods stay editable.
- **Rate is immutable after creation** (also for custom codes): a changed percentage would silently change the meaning of past lines; the user adds a new code ("BTW 9%" stays, a future "BTW x%" is a new code).
- **Codes are deactivated, never deleted**: lines reference them forever (bewaarplicht); deactivating a code that is still an account's default is refused instead of silently dropping the suggestion.
- **No KOR code seeded**: KOR means no btw aangifte at all, so a seeded code would imply a rubriek that does not exist. The glossary explains KOR; a user on KOR adds a 0% code with empty rubrieken. (Business default chosen; revisit when the BTW-aangifte feature handles KOR.)
- **Three boolean flags instead of a join table or text list**: only three fixed contexts exist (inkoop, verkoop, bank); booleans keep queries and migration trivial. A fourth context (e.g. kas) would be a new migration; kas follows "bank".
- **Manual boeking keeps all accounts**: it is the memoriaal escape hatch, and hiding there would make unusual bookings impossible.
- **Inbox list can include asset accounts** (0100/0110/0120 are purchase-selectable): needed for buying a laptop; the AI auto-suggestion still only picks expense accounts (existing rule), which is acceptable.
- **Suggestion is JS-prefill, not server rewriting**: server-side re-render after a validation error must not overwrite the user's choice; the script respects a touched select.
- **Backfill is data-driven from the seed module** (not hard-coded in the migration body) so tests and `add_account` share the same rules; unknown/user-added accounts in an existing database get type-based defaults (rules in criterion 2, applied by SQL on `type` and the explicit code lists).
- Risk: the three-parts-touch-`vat-suggest.js` coupling; mitigated by the fixed selector contract in Part 5/6.
- Risk: `tests/test_help_page.py` asserts the exact settings nav; Part 4 updates it, and Part 7's plain-language test depends on Parts 4/5 being merged, so reviewers run the full suite only after integration.
