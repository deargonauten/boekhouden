Status: APPROVED

# Spec: Relaties (klanten en leveranciers)

## 1. Goal and context
The bookkeeping app needs a register of the people and companies the user does business with (relaties). Later features (document inbox, AI extraction, purchase booking, sales invoices, bank reconciliation) all reference a relation. This feature delivers:
1. A `contact` table and CRUD UI under the existing sidebar item "Relaties" (`/relaties`, currently a placeholder).
2. Validation and normalization of KvK, BTW-nummer and IBAN.
3. A pure-ish domain service `match_or_create_contact(...)` that the later extraction flow calls with extracted supplier/customer data. No extraction code is built here.

Existing conventions to follow (see repo): domain code in `app/domain/<area>/` with a `__init__.py` public API; SQLAlchemy 2.0 models in `app/models/` (re-exported in `app/models/__init__.py`); domain errors are `LedgerError` subclasses with stable `code` and Dutch `message` (`app/domain/errors.py`); thin route handlers in `app/web/*_routes.py` using `_render` / 303 redirects, HTMX boost, templates under `app/web/templates/`; glossary in `app/domain/glossary.py`; Alembic migrations in `migrations/versions/` (latest: `0002_core_ledger`); web tests use the `client` fixture, domain/service tests use the `engine`/`session` fixtures pattern from `tests/ledger/conftest.py`.

## 2. Non-goals
- No extraction, inbox, upload or Claude API code (only the service it will call).
- No invoices, balances, debiteuren/crediteuren totals per relation, no grootboek link per relation.
- No hard delete, no merge-duplicates UI, no import/export, no multiple IBANs / multiple addresses per relation, no contact persons, no KvK/VIES online lookup.
- No default grootboek/BTW-code per supplier (belongs to "Purchase booking flow").
- No authentication or permissions.

## 3. User stories
- As the owner I can add a klant or leverancier (or both) with name, KvK, BTW-nummer, IBAN and address, and the app tells me in plain Dutch when a number is mistyped.
- I can find a relation via search and filter on klant/leverancier.
- I can edit a relation, and archive it when I no longer use it (it disappears from default lists and future pickers but old bookings keep their link), and restore it.
- When an invoice is read automatically later, the app finds the existing supplier by BTW-nummer, KvK, IBAN or name, or creates it, so I do not get duplicates.

## 4. Acceptance criteria

### Data and validation
1. Table `contact` exists via Alembic migration `0003_relations` (down_revision `0002_core_ledger`), with upgrade and downgrade; `alembic check` shows no drift; `tests/test_migrations.py` head assertion is updated to `0003_relations`.
2. Fields: `name` (required, 1-200 chars after trim), `is_customer` (bool), `is_supplier` (bool; at least one of the two must be true), `kvk` (8 digits, optional), `btw_number` (optional), `iban` (optional), `address_line` (street + number, optional), `postal_code`, `city`, `country` (ISO 3166 alpha-2, default `NL`), `email`, `phone`, `notes` (all optional), `name_key` (derived, see 5), `is_active` (default true), `created_at`, `updated_at`. Empty strings are stored as NULL.
3. KvK: normalized by stripping spaces/dots/hyphens; valid iff exactly 8 digits. Otherwise error: "Een KvK-nummer bestaat uit 8 cijfers, bijvoorbeeld 12345678. Controleer het nummer."
4. BTW-nummer: normalized to uppercase without spaces, dots and hyphens. Dutch numbers (prefix `NL`) must match `^NL[0-9]{9}B[0-9]{2}$`; no elfproef check (modern NL BTW numbers for eenmanszaken do not satisfy it). Other EU/foreign numbers (prefix of two letters other than NL) pass a loose check `^[A-Z]{2}[0-9A-Z]{2,12}$` so EU suppliers (verlegd/ICP, later) can be stored. Error: "Een Nederlands btw-nummer ziet eruit als NL123456789B01 (NL, 9 cijfers, B, 2 cijfers). Controleer het nummer."
5. IBAN: normalized to uppercase without spaces; valid iff `^[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}$`, ISO 13616 mod-97 check equals 1, and for `NL` length is exactly 18. Error: "Dit IBAN klopt niet (controlecijfers kloppen niet). Controleer het rekeningnummer, bijvoorbeeld NL91 ABNA 0417 1643 00." Display format groups by 4 (`format_iban`); stored unspaced.
6. Email, if given, needs a simple `x@y.z` shape; postal code is free text (foreign formats), max 12 chars. Error texts are plain Dutch and tell what to do.
7. Uniqueness: normalized `kvk`, `btw_number` and `iban` are each unique across ALL contacts (active and archived) via partial unique indexes (`WHERE col IS NOT NULL`). Creating/editing into a duplicate gives: "Er bestaat al een relatie met dit KvK-nummer: <naam>. Open die relatie in plaats van een nieuwe aan te maken." (analogous for btw-nummer and IBAN); HTTP 409 in the UI.
8. All validation lives in `app/domain/relations/`; every validation failure raises a `RelationError` (subclass of `LedgerError`) with stable `code` (`INVALID_KVK`, `INVALID_BTW_NUMBER`, `INVALID_IBAN`, `INVALID_EMAIL`, `NAME_REQUIRED`, `ROLE_REQUIRED`, `DUPLICATE_KVK`, `DUPLICATE_BTW_NUMBER`, `DUPLICATE_IBAN`, `CONTACT_NOT_FOUND`) and Dutch message. A form with several invalid fields reports all of them at once (collect errors, do not stop at the first). Missing role message: "Kies of dit een klant, een leverancier of allebei is."

### CRUD UI (Dutch)
9. Sidebar "Relaties" (`/relaties`) is served by a real router, not the placeholder (`LEDGER_KEYS`/registration in `app/web/routes.py` updated so the placeholder is not registered for `relaties`).
10. `GET /relaties`: table with Naam, Soort (Klant / Leverancier / Beide), KvK, BTW-nummer, IBAN (formatted), Plaats, Status; filter on soort (Alle / Klanten / Leveranciers), search box `q` (case-insensitive match on name, KvK, BTW-nummer, IBAN, city), checkbox "Toon ook gearchiveerde relaties" (default off). Sorted by `name_key`. Empty state in plain Dutch explaining what relations are and offering "Relatie toevoegen". Archived rows are visually muted and labelled "Gearchiveerd".
11. `GET/POST /relaties/nieuw`: form with the fields above; label text leads with plain Dutch and shows the term next to it with an info icon, e.g. "Bedrijfsnummer Kamer van Koophandel (KvK-nummer) (i)". Default suggestions: country `NL`, soort preselected from `?soort=klant|leverancier` query (else "Leverancier" checked, because supplier invoices are processed first); `?naam=` prefill optional. Valid POST redirects (303) to `/relaties` with a confirmation line "Relatie <naam> is toegevoegd."; invalid POST re-renders with 422 (409 for duplicates), keeps the entered values, and lists all errors (using the `ledger/_error.html` pattern or a relations equivalent).
12. `GET/POST /relaties/{id}/bewerken`: same form prefilled; saves via domain service; unknown id gives 404 page.
13. `POST /relaties/{id}/archiveren` and `/relaties/{id}/herstellen`: toggle `is_active`; no confirm page needed, but the button has a title "Verbergt de relatie in lijsten; bestaande boekingen en facturen blijven bewaard." There is NO delete route and no delete button anywhere (a test asserts `DELETE /relaties/{id}` and any `/verwijderen` path return 404/405).
14. Archiving is allowed regardless of usage (nothing references contacts yet); archived contacts keep all data.
15. Money is not involved. All new pages are added to `PAGES` in `tests/test_plain_language.py`.

### Plain-language requirements (CLAUDE.md)
16. New glossary entries in `app/domain/glossary.py` (each: plain phrase, <=220 char explanation, no guarded jargon words per existing tests, `detect` regex where needed):
    - `kvk` ("KvK-nummer", plain: "Inschrijfnummer van je bedrijf", detect `\bkvk(-nummer)?\b`): the 8-digit registration number from the Kamer van Koophandel; shown on invoices of businesses.
    - `btw_nummer` ("Btw-nummer", plain: "Btw-identificatienummer van een bedrijf", detect `\bbtw-nummer\b`): number like NL123456789B01 that identifies a business for VAT; needed for correct btw-aangifte and for EU purchases.
    - `iban` ("IBAN", plain: "Bankrekeningnummer", detect `\biban\b`): international bank account number; used to recognise who a payment is to or from.
    - `klant` ("Klant", plain: "Iemand aan wie je verkoopt") and `leverancier` ("Leverancier", plain: "Iemand bij wie je inkoopt"), detect `\bklanten?\b` / `\bleveranciers?\b` set to `(_NEVER,)` if they would force icons on every sentence (builder decides; they must still be used with `info()` on the form and list headers).
    - `archiveren` ("Archiveren", plain: "Verbergen zonder te verwijderen"): hides the relation from lists; boekingen are kept because the law requires keeping records for 7 years.
    Existing `relaties` entry is reused. The `btw` detect regex `\bbtw\b(?!-code)` must be extended to `(?!-code|-nummer)` so "Btw-nummer" is governed by `btw_nummer`.
17. Every term occurrence on the new pages passes `tests/web_helpers` checks (`assert_plain_language`); every new glossary key is used by a template (the "unused key" test must pass without growing `UNUSED_OK`).
18. Plain-Dutch helper text under fields: KvK ("8 cijfers, staat op de factuur of in het Handelsregister"), BTW-nummer ("Begint met NL, bijvoorbeeld NL123456789B01. Buitenlandse nummers mag je ook invullen."), IBAN ("Wordt gebruikt om betalingen straks automatisch aan de juiste relatie te koppelen.").
19. Error messages from `RelationError` are shown verbatim to the user and contain no codes/exception text; a domain test checks every `RelationError` message for the absence of raw code words and presence of an actionable hint (follow `tests/domain/test_error_messages.py` pattern).

### Match-or-create service
20. Public function `match_or_create_contact(session, data: ExtractedContact, role: Literal["supplier","customer"], *, create: bool = True) -> MatchResult` in `app/domain/relations/matching.py`, exported from `app.domain.relations`. `ExtractedContact` is a frozen dataclass: `name: str | None`, `kvk`, `btw_number`, `iban`, `address_line`, `postal_code`, `city`, `country`, `email`, `phone` (all `str | None`, raw as extracted). `MatchResult` is a frozen dataclass: `contact: Contact | None`, `status: Literal["matched","created","ambiguous","not_found"]`, `matched_on: Literal["btw_number","kvk","iban","name"] | None`, `candidates: tuple[Contact, ...]` (only for ambiguous), `warnings: tuple[str, ...]` (Dutch, user-readable).
21. Matching order, first hit wins: (1) BTW-nummer, (2) KvK, (3) IBAN, (4) normalized name. Identifiers are normalized with the same functions as validation. Identifier matches look at active AND archived contacts.
22. Extracted data may be wrong, so invalid identifiers never raise: an invalid KvK/BTW/IBAN/email is ignored for matching and for storing, and adds a warning like "Het btw-nummer 'NL12' op de factuur is ongeldig en is genegeerd."
23. If a higher-priority key matches contact A and a lower-priority key points to a different contact B, A is returned and a warning is added: "Het IBAN op de factuur hoort bij <B.naam>, maar het btw-nummer hoort bij <A.naam>. Controleer of dit dezelfde relatie is."
24. Name matching: only if no identifier matched. Compare `name_key` (see 26) against ACTIVE contacts only. Exactly one hit: `matched`, `matched_on="name"`. Two or more hits: `status="ambiguous"`, `candidates` filled, nothing created or changed. Name matching is skipped when `name` is empty after normalization.
25. On a match the contact is enriched but never overwritten: empty fields (kvk, btw_number, iban, address fields, email, phone) are filled from valid, non-conflicting extracted values (a value that would violate a unique index because another contact owns it is skipped with a warning); non-empty fields are untouched; the requested role flag is set to true if it was false; an archived contact matched by identifier is reactivated and a warning "Relatie <naam> was gearchiveerd en is weer actief gemaakt." is added. The session is flushed, not committed (caller owns the transaction).
26. Normalized name (`normalize_name`) : Unicode NFKD, strip diacritics, casefold, replace `&` with `en`, remove punctuation, collapse whitespace, then drop trailing legal-form tokens (`bv`, `b v`, `nv`, `vof`, `v o f`, `cv`, `eenmanszaak`, `ltd`, `llc`, `inc`, `gmbh`, `sarl`, `bvba`, `sa`) and a leading `de`/`het`/`the` only for comparison. Example: "Jansen & Zn. B.V." == "jansen en zn" ; "Café De Pijp" == "Cafe de Pijp". If the result would be empty (name consisted only of legal tokens), `name_key` is the plain casefolded name. `name_key` is stored on the row and recomputed on every name change by the service (single place).
27. No match and `create=True`: a new active contact is created with the requested role, valid extracted fields, `country` defaulting to `NL`; requires a non-empty name, else status `not_found`, `contact=None`, warning "Er is geen naam of bedrijfsgegeven gevonden om een relatie op aan te maken." With `create=False`: status `not_found`, nothing written.
28. The function is idempotent: calling it twice with the same data yields `created` then `matched` (same contact id), never two rows.
29. Ordering of the data model: a contact created by this service is validated by the same code path as UI-created contacts (shared `normalize_*`/`validate_*` functions), so it cannot bypass validation.

## 5. Technical approach

### Package layout
```
app/domain/relations/__init__.py      public API
app/domain/relations/validation.py    pure: normalize_kvk/btw/iban/email, validate_*, format_iban, normalize_name, ContactInput, collect errors
app/domain/relations/service.py       DB: create/update/get/list/set_active (uses Session)
app/domain/relations/matching.py      ExtractedContact, MatchResult, match_or_create_contact
app/models/relations.py               Contact model (re-export in app/models/__init__.py)
migrations/versions/0003_relations.py
app/web/relations_routes.py           router for /relaties*
app/web/templates/relations/{list,form,_error}.html
```
Errors: add codes + `RelationError(LedgerError)` subclasses to `app/domain/errors.py` using the existing `_error_class` helper (or in `relations/errors.py` re-using `LedgerError`; builder chooses, but codes must be as listed in AC 8).

### Data model (`contact`)
`id` PK; `name` TEXT NOT NULL; `name_key` TEXT NOT NULL (indexed, non-unique); `is_customer` BOOL NOT NULL default 0; `is_supplier` BOOL NOT NULL default 0; CHECK `is_customer OR is_supplier`; `kvk` TEXT NULL CHECK (`kvk IS NULL OR (length(kvk)=8 AND kvk NOT GLOB '*[^0-9]*')`); `btw_number`, `iban` TEXT NULL; `address_line`, `postal_code`, `city` TEXT NULL; `country` TEXT NOT NULL default 'NL' CHECK length 2; `email`, `phone`, `notes` TEXT NULL; `is_active` BOOL NOT NULL default 1; `created_at`, `updated_at` DATETIME NOT NULL. Unique partial indexes: `uq_contact_kvk`, `uq_contact_btw_number`, `uq_contact_iban` (`WHERE <col> IS NOT NULL`, via `sqlite_where`). Index on `is_active`. Rows are never deleted by code; no delete function exists in the service. The migration must not import `app.models` (same rule as 0002). The model must declare the same indexes/constraints so `alembic check` is clean (render_as_batch is on; no triggers involved on this table).

### Service API
`create_contact(session, data: ContactInput) -> Contact`, `update_contact(session, contact_id, data) -> Contact`, `get_contact`, `list_contacts(session, *, role=None, q=None, include_archived=False) -> list[Contact]`, `set_contact_active(session, contact_id, active: bool)`. `ContactInput` is a frozen dataclass of raw strings + the two role bools; `validate_contact_input(data) -> NormalizedContact` returns normalized values or raises a `RelationError` carrying all individual messages (`.messages: list[str]`, `str()` joins them). Duplicate detection: check explicitly before insert/update (to give the named message) AND rely on the unique index as a backstop (catch `IntegrityError` -> map to the duplicate error). `updated_at` set in the service.

### Web
`relations_routes.py` mirrors `ledger_routes.py` (`_render`, `_see_other`, status mapping: validation 422, duplicate 409, not found 404). Handlers parse form fields, build `ContactInput`, call the service, render. No logic in handlers. Include the router in `app/web/routes.py` before the placeholder loop, and add `"relaties"` to the set of keys skipped by `_register`. Use `partials/_info.html` macros (`term_label`, `info`). Reuse existing CSS classes (`data`, `table-wrap`, `btn`, `btn-secondary`, `inline-form`, `inactive`); add only minimal new CSS in `app/web/static/app.css` if needed.

### Flow: extraction (future) 
Extraction flow calls `match_or_create_contact(session, ExtractedContact(...), "supplier")`, shows `warnings` and, for `ambiguous`, lets the user pick among `candidates`. Nothing in this feature depends on the extraction feature.

## 6. Work breakdown
Part A - Domain validation + errors (no DB). Owns `app/domain/relations/validation.py`, `app/domain/errors.py` (relation codes), `tests/domain/test_relations_validation.py`, `tests/domain/test_relations_error_messages.py`. No dependencies. Provides the interfaces `ContactInput`, `NormalizedContact`, `normalize_*`, `format_iban`, `normalize_name`.
Part B - Model + migration + service. Owns `app/models/relations.py`, `app/models/__init__.py` (one-line export), `migrations/versions/0003_relations.py`, `app/domain/relations/service.py`, `app/domain/relations/__init__.py`, `tests/relations/` (conftest, test_service, test_schema), `tests/test_migrations.py` (head version update). Depends on Part A's interfaces (agree signatures from section 5 up front; B may stub until A lands).
Part C - Match-or-create. Owns `app/domain/relations/matching.py`, `tests/relations/test_matching.py`. Depends on A (normalization) and B (model + service). Can be written against the model signature in parallel and integrated after B.
Part D - UI + glossary. Owns `app/web/relations_routes.py`, `app/web/templates/relations/*`, `app/web/routes.py` (relaties wiring), `app/domain/glossary.py` (new terms + btw regex), `tests/domain/test_glossary.py` (REQUIRED list), `tests/test_relations_web.py`, `tests/test_plain_language.py` (add PAGES), optional CSS. Depends on B's service API (and A's errors); integration point is `ContactInput` and `RelationError.messages`.
Integration points: `app/domain/relations/__init__.py` exports (B owns, A and C add their names); `app/domain/errors.py` (A only); `app/models/__init__.py` (B only).

## 7. Test strategy (tests first for validation and matching; they involve identifiers that drive VAT later)
- Validation unit tests: KvK (valid, 7/9 digits, letters, spaced/dotted input normalizes), BTW (NL valid, `NL123456789B1` invalid, lowercase/spaced input, `DE123456789` accepted, junk rejected), IBAN (known-valid: `NL91ABNA0417164300`, `DE89370400440532013000`, `BE68539007547034`; flipped digit fails; NL wrong length fails; lowercase/space input normalizes; `format_iban`), email, name required, role required, multiple errors collected together.
- `normalize_name` table-driven cases (diacritics, `&`, legal suffixes, punctuation, only-legal-token names, leading "de").
- Service tests: create/update/list filters/search/archive/restore, `updated_at` changes, empty strings become NULL, duplicate KvK/BTW/IBAN (also against an archived contact) raise the right error with the other contact's name, no delete API exists (`not hasattr`).
- Schema tests: CHECK constraints (role, kvk), unique partial indexes allow multiple NULLs; migration upgrade/downgrade/check.
- Matching tests: each key in isolation; priority order; conflict warning; archived match by identifier reactivates; name match only active; ambiguous name; invalid identifiers ignored with warning; enrichment fills only empty fields and never overwrites; role added on match; unique-conflict enrichment skipped with warning; create with/without name; `create=False`; idempotency; no commit by the service (rollback in test discards the row).
- Web tests (`client` fixture): list empty state, create (valid, invalid with multiple errors and kept values 422, duplicate 409), edit, archive/restore, list filters/search/archived toggle, no delete route, 404 for unknown id, `/relaties` no longer renders the placeholder.
- Plain-language tests: new pages in `PAGES`, all new glossary entries valid and used, `btw` regex change does not break existing pages.
- Full existing suite stays green.

## 8. Risks and decisions made
- One `contact` table with `is_customer`/`is_supplier` flags (not two tables): the same company can be both; later features filter by flag.
- One IBAN and one address per relation: keeps matching deterministic and the form simple; multiple IBANs can be added later with a child table. Consequence: a supplier invoice showing a second IBAN fills nothing and is ignored (no warning needed beyond the conflict case).
- Identifier uniqueness across archived contacts too, with identifier matches reactivating archived contacts: avoids duplicate rows and index violations; documented by a warning.
- Name matching is limited to active contacts and refuses to guess when ambiguous: a wrong automatic link would put VAT on the wrong relation; the caller must ask the user.
- NL BTW format-only (no elfproef): sole-proprietor numbers issued since 2020 are not elfproef-valid, so a checksum would reject real numbers. Foreign numbers get only a loose shape check; no VIES lookup.
- Matching never raises on bad extracted data (AI output is unreliable); it degrades to warnings.
- The service flushes but never commits: the later booking flow must be able to roll back a whole approval.
- Archiving has no "in use" guard now because nothing references contacts; later features that reference `contact.id` should use a FK and may add guards.
- Glossary `btw` regex tweak is needed because the existing pattern would demand a separate icon on the word "Btw" inside "Btw-nummer".
