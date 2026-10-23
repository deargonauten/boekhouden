Status: APPROVED

# Spec: Bedrijfsgegevens (feature 35)

## 1. Goal and context
The owner is the only user of this app and runs an eenmanszaak/VOF. Facturen (art. 35a Wet OB) and the BTW-aangifte need their own naam, adres, KvK-nummer, btw-id and IBAN. Today these live nowhere. This feature adds one settings screen, **Instellingen > Bedrijfsgegevens**, that stores them (a single row), validates them, and gives other modules a read API in `app/domain/company/`.

Existing code to reuse (verified in repo):
- `app/domain/relations/validation.py`: `normalize_kvk`/`is_valid_kvk`, `normalize_iban`/`is_valid_iban` (mod-97 plus NL length 18)/`format_iban`, `validate_email`, `validate_country`, `validate_postal_code`. Reuse the normalizers and `is_valid_*` checks; do not copy the regexes. (`validate_btw_number` accepts foreign ids, so company gets its own strict NL check.)
- `RelationError` in `app/domain/errors.py`: one error carrying many messages (`combine`, `messages`). The company errors subclass it.
- Settings UI: `base_settings.html`, `ledger/_settings_nav.html` (`settings_header`), `SETTINGS_NAV` in `app/web/navigation.py`, `partials/_ui.html` (`error_box`, `page_header`), `partials/_info.html` (`info`, `term_label`), form markup of `relations/form.html` (`card`, `form-grid`, `field`, `field__hint`).
- Route pattern of `app/web/relations_routes.py` (`_render`, POST then `session.commit()`, 303 redirect on success, 422 with values re-shown on error).
- There is NO KvK lookup in the repo; none is built here (see non-goals).

## 2. Non-goals
- No KvK-register / BTW-VIES lookup or auto-fill (needs external API and key; later feature).
- No logo, factuurnummerreeks, betaaltermijn, factuurtemplate (invoice feature).
- No KOR setting, urencriterium, partner details for the VOF (own backlog items).
- No history/versioning of the company row (see risks).
- No multiple companies, no per-user settings.

## 3. User stories
- As ondernemer I fill in my naam, adres, KvK, btw-id and IBAN once, so facturen and aangifte can use them.
- As ondernemer I get a clear Dutch message when a number is mistyped and I keep what I typed.
- As ondernemer I can see at a glance what is still missing for invoicing.
- As developer of the invoice/BTW modules I call one function to get the company data, or a clear error saying what is missing.

## 4. Acceptance criteria

### Screen
1. `GET /instellingen/bedrijfsgegevens` shows a form, prefilled with the stored values (empty on first use; `country` suggested as `NL`, `legal_form` suggested as `eenmanszaak`). Page uses `base_settings.html` and `settings_header("Bedrijfsgegevens")`, breadcrumb Instellingen > Bedrijfsgegevens, and a lead sentence in plain Dutch ("Dit zijn de gegevens van jouw bedrijf. Ze komen straks op je verkoopfacturen en in je btw-aangifte.").
2. The settings navigation (`SETTINGS_NAV`) gets a new FIRST group "Mijn bedrijf" with item "Bedrijfsgegevens" (`/instellingen/bedrijfsgegevens`, `term_key="bedrijfsgegevens"`). The existing group "Boekhouding" stays. `/instellingen` keeps redirecting to `/instellingen/grootboek` (no behaviour change).
3. Fields (label in plain Dutch, name in form):
   - `legal_name` "Naam van je bedrijf of je eigen naam" (required, max 200)
   - `trade_name` "Handelsnaam (als die anders is)" (optional, max 200)
   - `legal_form` "Rechtsvorm": radio/select `eenmanszaak` | `vof`, default `eenmanszaak`
   - `address_line` "Adres (straat en huisnummer)", `postal_code` "Postcode", `city` "Plaats", `country` "Land (2 letters)", default `NL`
   - `kvk` "Inschrijfnummer Kamer van Koophandel" (KvK-nummer)
   - `btw_id` "Btw-identificatienummer" (btw-id)
   - `iban` "Bankrekeningnummer" (IBAN)
   - `email`, `phone` (optional; shown on invoices later)
4. Saving: `POST /instellingen/bedrijfsgegevens`. Only `legal_name` is required to save (people may fill it in step by step). Success: 303 redirect to `/instellingen/bedrijfsgegevens?opgeslagen=1`, which shows the flash "Bedrijfsgegevens opgeslagen." Errors: HTTP 422, form re-rendered with everything the user typed, all problems listed together in `error_box`, nothing saved.
5. Completeness banner on the page: when required-for-invoice fields are missing, a notice (not an error) says in plain Dutch which ones: "Voor het maken van facturen ontbreekt nog: adres, KvK-nummer, btw-id." When complete: "Je bedrijfsgegevens zijn compleet voor facturen." Required-for-invoice = `legal_name`, `address_line`, `postal_code`, `city`, `kvk`, `btw_id`, `iban`.
6. Re-saving updates the single row; there is never more than one row (DB enforced).

### Validation (all in domain, none in the route)
7. `kvk`: spaces, dots and hyphens are stripped; must then be exactly 8 digits. Message: "Je KvK-nummer bestaat uit 8 cijfers, bijvoorbeeld 12345678. Controleer het nummer."
8. `btw_id`: spaces/dots/hyphens stripped, uppercased; must match `^NL[0-9]{9}B[0-9]{2}$` (Dutch only; own company is Dutch). Message: "Je btw-id ziet eruit als NL123456789B01 (NL, 9 cijfers, de letter B en 2 cijfers). Controleer het nummer." A btw-id of a Dutch eenmanszaak that is a BSN-based old number is not accepted; the 2023 format (omzetbelastingnummer NL...B..) is the one required. No elfproef (11-proef) check: a valid-format but non-existent number is not detectable offline. Hint in UI: "Staat op je btw-aangifte en op brieven van de Belastingdienst."
9. `iban`: spaces removed, uppercased; must pass `is_valid_iban` (format, NL length 18, mod-97). Displayed grouped by four (`format_iban`), stored unspaced. Message: "Dit IBAN klopt niet (de controlecijfers kloppen niet). Controleer je rekeningnummer, bijvoorbeeld NL91 ABNA 0417 1643 00."
10. `postal_code`: for country NL it must be 4 digits + 2 letters (optional space, any case) and is stored normalized as `1234 AB`. Message: "Een Nederlandse postcode bestaat uit 4 cijfers en 2 letters, bijvoorbeeld 1234 AB." For other countries only a max length of 12.
11. `country`: via `validate_country` (two letters, default NL). `email` via `validate_email`. `legal_form` must be one of the two values, otherwise: "Kies eenmanszaak of vof als rechtsvorm."
12. `legal_name` empty: "Vul de naam van je bedrijf of je eigen naam in." Longer than 200 (also `trade_name`): "Deze naam is te lang (maximaal 200 tekens). Kort de naam in."
13. Empty optional fields are stored as NULL. Multiple invalid fields produce one `CompanyError` with all messages (like `validate_contact_input`).
14. No message shows a raw exception or only a code.

### Read API for other modules
15. `get_company_profile(session) -> CompanyProfile`: frozen dataclass (not ORM object), always returns an instance (fields `None` when nothing stored yet). Never raises for an empty table.
16. `CompanyProfile.missing_for_invoice() -> list[str]` returns the Dutch labels of missing required fields in form order; `CompanyProfile.is_complete_for_invoice` is `not missing_for_invoice()`. Also `address_lines() -> list[str]` (street; "1234 AB Plaats"; country name omitted when NL) and `iban_display`.
17. `require_company_for_invoice(session) -> CompanyProfile` raises `CompanyIncompleteError` (code `COMPANY_INCOMPLETE`) with message "Vul eerst je bedrijfsgegevens aan onder Instellingen > Bedrijfsgegevens. Er ontbreekt: adres, KvK-nummer." when incomplete.
18. Everything is importable from `app.domain.company` only (public `__init__`), mirroring `app.domain.relations`.

### Plain-language requirement (CLAUDE.md)
Terms introduced, each with an entry in `app/domain/glossary.py` and used in a template via `info()`/`term_label()` (the test `test_every_glossary_key_is_used` fails on unused keys):
- `bedrijfsgegevens` "Bedrijfsgegevens": plain "Wie jij als ondernemer bent"; explanation: what they are and that they go on invoices and into the btw-aangifte. Also used as `term_key` of the settings nav item.
- `btw_id` "Btw-id": plain "Jouw btw-identificatienummer"; explanation: number like NL123456789B01, you need it on every sales invoice and for btw-aangifte; detect regex `\bbtw-id\b`.
- `handelsnaam` "Handelsnaam": plain "Naam waaronder je zaken doet"; for when it differs from your own name.
- `rechtsvorm` "Rechtsvorm": plain "Soort onderneming"; eenmanszaak (alone) or VOF (with a partner).
- Reuse existing `kvk` ("KvK-nummer") and `iban` ("IBAN"); `kvk`/`iban` info icons appear next to their labels. Existing `btw_nummer` stays untouched (it describes a relation's number).
- Each explanation max 220 chars (existing glossary test).
Suggested defaults: country `NL`, rechtsvorm `eenmanszaak`. Hints under fields as in criteria 7-10. The page `/instellingen/bedrijfsgegevens` (empty and filled) and the error state are added to `pages()` in `tests/test_plain_language.py` so `assert_plain_language` covers them.

## 5. Technical approach

### Data model (`app/models/company.py`, exported from `app/models/__init__.py`)
Table `company_profile`:
- `id` INTEGER PK, `CHECK (id = 1)` (single row)
- `legal_name` TEXT NOT NULL, `trade_name` TEXT NULL
- `legal_form` TEXT NOT NULL default `'eenmanszaak'`, `CHECK (legal_form IN ('eenmanszaak','vof'))`
- `address_line`, `postal_code`, `city` TEXT NULL; `country` TEXT NOT NULL default `'NL'`, `CHECK (length(country)=2)`
- `kvk` TEXT NULL, `CHECK (kvk IS NULL OR (length(kvk)=8 AND kvk NOT GLOB '*[^0-9]*'))` (same pattern as `contact`)
- `btw_id` TEXT NULL, `CHECK (btw_id IS NULL OR (length(btw_id)=14 AND btw_id GLOB 'NL[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]B[0-9][0-9]'))`
- `iban`, `email`, `phone` TEXT NULL
- `created_at`, `updated_at` DateTime NOT NULL
No row exists until the first save; `save_company_profile` inserts with `id=1` or updates it. Money is not involved.

### Migration
`migrations/versions/0006_company_profile.py`, `revision = "0006_company_profile"`, `down_revision = "0005_invoice_extraction"`. Style of 0005 (no `app.models` import, explicit `sa.Column`, named CheckConstraints `ck_company_profile_*`). `downgrade` drops the table. `tests/test_migrations.py` head assertion updated to `["0006_company_profile"]`.

### Domain (`app/domain/company/`)
- `validation.py`: pure. `CompanyInput` (frozen dataclass of raw strings: the 12 form fields, all default None), `NormalizedCompany`, `normalize_btw_id`, `is_valid_btw_id`, `validate_btw_id`, `validate_nl_postal_code(raw, country)`, `validate_company_input(data) -> NormalizedCompany` (collects all errors, `CompanyError.combine`). Reuses relations normalizers/validators for kvk, iban, email, country; wraps their `RelationError` into `CompanyError` with the tailored messages above (messages from relations validators for kvk/iban are replaced by the company wording). Unit: `format_iban` re-exported.
- `service.py`: `get_company_profile(session)`, `save_company_profile(session, data: CompanyInput) -> CompanyProfile` (flush, caller commits, same as relations), `require_company_for_invoice(session)`. `CompanyProfile` lives in `profile.py` (dataclass + `missing_for_invoice`, `address_lines`, `iban_display`, `REQUIRED_FOR_INVOICE` tuple of (field, Dutch label)). Labels: naam, adres, postcode, plaats, KvK-nummer, btw-id, IBAN.
- `__init__.py` public API: `CompanyInput`, `CompanyProfile`, `CompanyError`, `CompanyIncompleteError`, `get_company_profile`, `save_company_profile`, `require_company_for_invoice`, `format_iban`.
- Errors in `app/domain/errors.py` (new section "Bedrijfsgegevens"): `class CompanyError(RelationError)` with code `COMPANY_ERROR`, subclasses via `_relation_error`-style helper: `InvalidCompanyKvkError` (`INVALID_COMPANY_KVK`), `InvalidCompanyBtwIdError` (`INVALID_COMPANY_BTW_ID`), `InvalidCompanyIbanError` (`INVALID_COMPANY_IBAN`), `InvalidCompanyPostalCodeError`, `InvalidCompanyLegalFormError`, `CompanyNameRequiredError` (`COMPANY_NAME_REQUIRED`), `CompanyNameTooLongError`, `CompanyIncompleteError` (`COMPANY_INCOMPLETE`). All inherit `CompanyError` so `.messages`/`combine` work (`RelationError.combine` is a classmethod, `CompanyError.combine` returns a `CompanyError`).

### Web (`app/web/company_routes.py`)
Thin routes: `GET`/`POST /instellingen/bedrijfsgegevens`. POST takes `Form("")` fields, builds `CompanyInput`, calls `save_company_profile` and `session.commit()`; on `CompanyError` rolls back and re-renders with `values` from the input, `errors=exc.messages`, status 422. Template filter `iban` is already registered globally by `relations_routes` (do NOT rely on import order: the company route registers its own `company_iban` usage via `CompanyProfile.iban_display` instead). Template `app/web/templates/company/form.html` extends `base_settings.html`, includes the completeness notice and flash. Router registered in `app/web/routes.py` (`router.include_router(company_router)`) before the nav placeholders; `"instellingen"` is already in `LEDGER_KEYS`. Styles: reuse `relations.css` classes via a small `static/css/company.css` only if needed (new file, owned by part B); no changes to existing CSS.

### Error handling
Domain raises `CompanyError`; route renders messages. Unexpected DB errors are not caught (single-user local app). The DB CHECK constraints are a second line of defence only.

## 6. Work breakdown (disjoint file ownership)

### Part A: domain, schema, migration, glossary
Owns (create/edit only these):
- `app/domain/company/__init__.py`, `validation.py`, `profile.py`, `service.py`
- `app/domain/errors.py` (append the Bedrijfsgegevens section only)
- `app/models/company.py`, `app/models/__init__.py`
- `migrations/versions/0006_company_profile.py`, `tests/test_migrations.py`
- `app/domain/glossary.py` (add `bedrijfsgegevens`, `btw_id`, `handelsnaam`, `rechtsvorm`)
- Tests: `tests/domain/test_company_validation.py`, `tests/domain/test_company_error_messages.py`, `tests/company/__init__.py`, `tests/company/conftest.py` (re-exports `engine, session` like `tests/relations/conftest.py`), `tests/company/test_schema.py`, `tests/company/test_service.py`, `tests/domain/test_glossary.py` only if a count assertion needs it.
Depends on: nothing. Write tests first (tdd skill), including the mod-97 and format cases.
Delivers the public API in section 5 exactly as named, because Part B codes against it.

### Part B: web, templates, navigation
Owns:
- `app/web/company_routes.py`, `app/web/templates/company/form.html`, `app/web/static/css/company.css` (optional)
- `app/web/navigation.py` (new `SETTINGS_NAV` group only), `app/web/routes.py` (router registration only)
- Tests: `tests/test_company_web.py`, `tests/test_plain_language.py` (add the three page states to `pages()`; add nothing else), `tests/test_ui_components.py` only if it asserts the settings nav contents.
Depends on: Part A's public API and glossary keys (names fixed in this spec, so work can start in parallel against the signatures; merge A first, then run all tests). Part B must not edit `glossary.py` or `errors.py`; if a key or error is missing it asks the spec writer.

Integration points: `from app.domain.company import ...`; glossary keys `bedrijfsgegevens`, `btw_id`, `handelsnaam`, `rechtsvorm`, `kvk`, `iban` referenced in the template; migration head `0006` needed by every DB-backed web test (conftest runs `alembic upgrade head`).

## 7. Test strategy
Domain (pytest, no DB unless noted):
- KvK: valid 8 digits, with spaces/dots, 7 digits, letters; empty becomes None.
- BTW-id: `NL123456789B01` ok, lowercase and spaced ok, `DE123456789` rejected, `NL12345678B01` rejected, `NL123456789B1` rejected.
- IBAN: `NL91ABNA0417164300` ok (spaced/lowercase ok), changed last digit fails checksum, NL with wrong length fails.
- Postal code NL normalization (`1234ab` -> `1234 AB`), bad NL code rejected, foreign code passes.
- Several bad fields give one `CompanyError` whose `messages` has all of them, all plain Dutch (assert on text, no code-only).
- Service (migrated sqlite via fixtures): empty profile returns empty `CompanyProfile`, `missing_for_invoice` lists all seven; save creates row id 1; second save updates (still one row, `updated_at` changes); partial save with only a name works; `require_company_for_invoice` raises with the missing list and passes when complete; `address_lines`.
- Schema: second row (id 2) rejected; bad kvk/btw_id/legal_form rejected by CHECK; migration upgrade/downgrade.
Web (`TestClient` as in `tests/test_relations_web.py`): GET empty form shows NL default; POST valid redirects 303 and flash shows; POST invalid returns 422 with typed values kept and every message visible; completeness notice lists missing items; settings nav shows "Bedrijfsgegevens" active on its page; `/instellingen` still redirects to grootboek; plain-language enforcement over the three page states; glossary key tests (`test_template_keys_exist_in_glossary`, `test_every_glossary_key_is_used`) pass.
Final gate: full `pytest` green.

## 8. Risks and decisions
- Single row via `CHECK (id = 1)` instead of a settings key/value table: typed columns can be validated by the DB and read directly by invoices.
- Only `legal_name` required to save, completeness reported separately: avoids blocking the user who only knows part of it, while invoice/aangifte code gets a hard gate through `require_company_for_invoice`.
- Own BTW check is strictly NL (the relation check accepts foreign ids); the own company is Dutch.
- No history: once invoices exist, an issued invoice must snapshot the company data at issue time (invoice feature responsibility, noted for that spec) because editing these settings must never alter an already issued invoice (Awr/art. 35a).
- `postal_code` strict only for NL; `country` kept editable but default NL because the app is NL-only.
- No external lookups (KvK API needs a key and contract); manual entry only.
- Part B uses `CompanyProfile.iban_display` rather than the `iban` Jinja filter registered in `relations_routes`, so there is no import-order coupling between route modules.
