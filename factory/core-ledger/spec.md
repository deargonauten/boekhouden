Status: APPROVED

# Spec: Core ledger

## Goal and context
Build the accounting kernel every later feature posts into: an RGS-referenced grootboekschema (seeded subset for an eenmanszaak/VOF), dagboeken, double-entry journal entries (integer cents, must balance, append-only with storno), VAT codes on lines, and boekjaren/periodes with locking. Builds on the existing skeleton (FastAPI + SQLAlchemy 2 sync + Alembic baseline `0001_baseline`, `app/domain/` empty, `Base` in `app/db.py`, nav item "Boeken" `/boeken` and "Instellingen" `/instellingen` currently placeholders). Business logic goes in `app/domain/`; routes only render/delegate.

## Non-goals
- No BTW-aangifte / rubriek derivation (only the VAT code on lines + VAT code reference table), no BTW calculation helpers beyond splitting nothing.
- No relations (contacts), documents, bank, invoices, assets; no `relation_id`/`document_id` columns yet (later features add them via migration). A generic `source_type`/`source_id` pair exists for later features to link back.
- No reports (balans, W&V, grootboekkaart pages). Only a trial-balance query function (needed for tests and a tiny UI total).
- No year-end closing entries / resultaatbestemming / carry-forward; no BV accounts (aandelenkapitaal, DGA, vpb).
- No multi-currency, no auth, no draft/concept entries (an entry is either posted or does not exist).
- No unlocking of locked periods (see decisions).

## User stories
- As the user I see a sensible default grootboekschema and dagboeken after first start, and can add my own grootrekeningen and deactivate unused ones.
- As the user I create a boekjaar (calendar year) and get 12 monthly periods.
- As the user I post a manual memoriaal-boeking with 2+ lines; unbalanced entries are rejected with a Dutch error message.
- As the user I cannot change or delete a booking; I can storno it, which creates an equal-and-opposite entry linked to the original.
- As the user I can lock a period (or close a whole boekjaar) so nothing can be booked or stornoed into it.

## Acceptance criteria
Money / validation (pure domain)
1. All amounts are `int` cents. `Money` helpers reject `float`/`bool`/`Decimal` input with `TypeError`. `parse_euro("1.234,56") == 123456`, accepts `"12"`, `"12,5"`, `"-3,00"`, `"€ 1,00"`; rejects `"1,234"`-style ambiguous input with a Dutch `ValueError`/`LedgerError`; `format_euro(123456) == "€ 1.234,56"` (negatives `"-€ 1,00"`).
2. A line has `debit_cents` and `credit_cents`, both `int >= 0`, exactly one `> 0` (a zero/zero or both-positive line is invalid).
3. An entry needs >= 2 lines, `sum(debit) == sum(credit)`, total > 0, a booking date, a non-empty description (<= 255 chars), and every line's account must exist, be active, and be postable (not a header/group account). Violations raise `LedgerError` subclasses with stable `code` attributes (`UNBALANCED`, `TOO_FEW_LINES`, `INVALID_LINE_AMOUNT`, `ACCOUNT_INACTIVE`, `ACCOUNT_NOT_FOUND`, `NO_OPEN_PERIOD`, `PERIOD_LOCKED`, `ALREADY_REVERSED`, `CANNOT_REVERSE_STORNO`, `INVALID_VAT_CODE`, `YEAR_EXISTS`, `YEAR_NOT_FOUND`, `ACCOUNT_IN_USE`) and a Dutch `message`.
4. VAT code on a line is optional; if given it must exist in `vat_code` and be active. VAT codes seeded: `GEEN` (geen btw), `NL_21` (21%), `NL_9` (9%), `NL_0` (0%), `VERLEGD` (btw verlegd), `EU_GOEDEREN` (intracommunautair goederen), `EU_DIENSTEN` (intracommunautair diensten), `EXPORT` (export buiten EU). Table columns: `code`, `name` (Dutch), `rate_bp` (basis points, 2100/900/0; null for non-percentage kinds is not allowed: use 0), `is_active`. The VAT *amount* itself is a normal separate line on a BTW account; the `vat_code` on a line marks which transaction type that line belongs to (base lines and VAT lines both carry it). No rubriek columns.

Posting
5. `post_entry(session, NewEntry) -> JournalEntry` inserts the entry and its lines atomically, assigns `entry_number` = `"{journal.code}-{fiscal_year}-{seq:04d}"`, with `seq` gapless and sequential per (journal, boekjaar) starting at 1; a failed/rolled-back post does not consume a number.
6. The `booking_date` must fall in an existing boekjaar whose period for that date has status `open`; else `NO_OPEN_PERIOD` / `PERIOD_LOCKED`. `period_id` is stored on the entry.
7. Entries have `kind` in `normal | opening | storno`. `opening` is allowed only in dagboek of type `memoriaal` and is used for the beginbalans (no special balancing rule beyond the normal one).
8. Entries and lines are immutable: any SQL `UPDATE` or `DELETE` on `journal_entry` or `journal_line` fails (SQLite triggers `RAISE(ABORT, ...)`); verified by raw-SQL tests, not just by absence of an API. Inserting a `journal_line` into an entry or inserting an entry into a locked period also fails at DB level (trigger).
9. `reverse_entry(session, entry_id, booking_date=None, description=None) -> JournalEntry` creates a `storno` entry in the same dagboek with every line's debit/credit swapped (account, vat_code and line description copied), `reverses_entry_id` = original id, default description `"Storno {original.entry_number}"`, default booking date = the original's date, or today if the original's period is locked (an explicit date in an open period always works). An entry can be reversed at most once (unique index on `reverses_entry_id`) and a storno entry cannot be reversed (book a new entry instead). The original is untouched; "reversed" status is derived (exists a storno), never stored.
10. Corrections beyond storno are just new normal entries; an optional `corrects_entry_id` is NOT introduced (YAGNI).

Grootboekschema
11. `account` table with: `id`, `code` (user-facing numeric string, unique, 4 digits), `name` (Dutch), `rgs_code` (nullable text, RGS reference code such as `BLimBan`), `type` in `asset | liability | equity | revenue | expense`, `is_postable` (bool; false for headers), `is_active`, `is_system` (seeded accounts: cannot be deleted, `code`/`type` not editable), `default_vat_code` (nullable FK, suggestion only). Normal balance side is derived from type (asset/expense = debit; others = credit).
12. Seed (via Alembic data migration, idempotent insert) contains the accounts listed under "Seed data", including the system accounts the later features will need: debiteuren, crediteuren, btw af te dragen hoog/laag/overig, btw verlegd, btw voorbelasting, btw rekening-courant (te betalen/ontvangen), kruisposten/ nog te boeken bank, privé-onttrekkingen/-stortingen, ondernemingsvermogen, algemeen/overig, kasverschillen. Each has an RGS reference where known.
13. Users can add accounts (code unique, 4 digits, type chosen) and deactivate/reactivate them, and rename non-system accounts. An account that has journal lines cannot be deleted (`ACCOUNT_IN_USE`); deletion of unused non-system accounts is allowed. Deactivated accounts cannot receive new lines.

Dagboeken
14. `journal` table: `id`, `code` (unique, <= 6 chars, uppercase), `name`, `type` in `verkoop | inkoop | bank | kas | memoriaal`, `account_id` (nullable FK; the bank/kas grootrekening for bank/kas types, required for those types), `is_active`. Seed: `VK` Verkoopboek, `IK` Inkoopboek, `BANK` Bank (-> 1210 Bank), `KAS` Kas (-> 1100), `MEM` Memoriaal. Users can add bank/kas dagboeken (needed later for multiple bankrekeningen) and deactivate; codes of used dagboeken are immutable; dagboeken are never deleted once used.
15. Type-consistency: a `bank`/`kas` dagboek's `account_id` must reference an active asset account.

Boekjaar / periodes
16. `fiscal_year`: `id`, `year` (unique int), `start_date`, `end_date`, `status` in `open | closed`. `create_fiscal_year(session, year)` creates the calendar year (1 jan - 31 dec) plus 12 monthly `period` rows (`number` 1..12, `start_date`, `end_date`, `status` `open | locked`, `locked_at` nullable). Duplicate year -> `YEAR_EXISTS`. Years are not required to be consecutive. Seed does NOT create a year; on first visit of the UI to `/instellingen/boekjaren` a prompt/button creates the current year. `create_fiscal_year` is also called implicitly never; booking in a year that doesn't exist fails `NO_OPEN_PERIOD` with message suggesting to create the boekjaar.
17. `lock_period(session, period_id)` sets status `locked` + `locked_at`. Idempotent. When all 12 periods are locked the fiscal year becomes `closed` (and `close_fiscal_year(session, year)` locks all remaining periods and sets `closed`). Locking is one-way: there is no unlock function, route, or SQL path (trigger allows only `open -> locked` transitions on `period` and `open -> closed` on `fiscal_year`; no deletes; other column updates rejected).
18. Locking order is free (any period may be locked), but `close_fiscal_year` requires nothing else. Periods cannot be created/deleted individually.
19. `trial_balance(session, *, fiscal_year=None, period_ids=None, up_to=None) -> list[TrialBalanceRow(account_id, code, name, debit_cents, credit_cents)]` sums line amounts per account (only accounts with movement), and the totals of debit and credit are equal for any dataset.

UI (minimal, Dutch labels)
20. `/boeken` replaces the placeholder: table of entries (newest first, 50 per page via `?page=`), filter by dagboek (`?dagboek=VK`), showing boekstuknummer, datum, dagboek, omschrijving, totaal; storno entries and entries that have been stornoed are labelled ("Storno van ..." / "Gestorneerd"). Button "Nieuwe boeking".
21. `/boeken/nieuw` form: dagboek (select), datum (default today), omschrijving, lines (grootrekening select showing `code naam`, debet, credit, optional btw-code select, optional line omschrijving), starts with 2 rows, "Regel toevoegen" via HTMX (partial row), live total/difference shown server-side on submit. Amounts typed in Dutch format. On error the form re-renders with Dutch messages and the input preserved (HTTP 422); on success redirects 303 to `/boeken/{id}`.
22. `/boeken/{id}` detail: header fields, lines, links to original/storno, and "Stornoboeking maken" (POST `/boeken/{id}/storno` with optional datum) shown only when reversible.
23. `/instellingen/grootboek`: list of accounts grouped by type with active toggle, add-account form. `/instellingen/dagboeken`: list + add form. `/instellingen/boekjaren`: list years with their periods and status, "Boekjaar aanmaken", per-period "Vergrendel periode", per-year "Boekjaar afsluiten" (with an `hx-confirm` dialog explaining it is permanent). `/instellingen` itself redirects (307) to `/instellingen/grootboek` and the Instellingen nav item stays active for these subpaths. Nav keys/paths in `navigation.py` are unchanged.
24. Currency rendering uses a Jinja filter `euro` (wrapping `format_euro`); no float arithmetic anywhere in templates or routes.
25. Route handlers only parse input, call a domain function, map `LedgerError` to a rendered message/HTTP status, and render. No ledger logic in routes.

Quality
26. `alembic upgrade head` from an empty DB creates all tables, triggers and seed; `downgrade base` removes them; `alembic check` shows no model/migration drift (triggers are created with `op.execute` and are not model-visible, so they must not break `check`).
27. All tests pass with `uv run pytest`; tests never touch `data/boekhouden.db`.

## Technical approach

### Package layout
```
app/domain/money.py            parse_euro, format_euro, require_cents
app/domain/errors.py           LedgerError(code, message) + code constants
app/domain/ledger/__init__.py  re-exports public API
app/domain/ledger/entries.py   NewLine, NewEntry dataclasses; validate_entry(); build_storno()  (pure, no DB)
app/domain/ledger/periods.py   generate_periods(year) -> list[PeriodSpec]; period_for_date(); (pure)
app/domain/ledger/service.py   DB-using: post_entry, reverse_entry, create_fiscal_year, lock_period,
                               close_fiscal_year, add_account, set_account_active, rename_account,
                               delete_account, add_journal, set_journal_active, trial_balance, queries
app/models/__init__.py         imports all models (so Base.metadata is complete)
app/models/ledger.py           SQLAlchemy 2 typed models (Mapped[...])
migrations/versions/0002_core_ledger.py   schema + triggers + seed
app/seed/rgs_accounts.py       SEED_ACCOUNTS, SEED_VAT_CODES, SEED_JOURNALS data (plain tuples/dataclasses, imported by the migration; migration must NOT import app.models)
app/web/ledger_routes.py       routes for /boeken*, /instellingen/*
app/web/templates/ledger/*.html
```
`migrations/env.py` must import `app.models` so autogenerate/check see the metadata (owned by the Models part; one-line change).

### Data model (table / column names are the contract between parts)
All money columns are `INTEGER` named `*_cents`. Dates are `DATE`. Timestamps `DATETIME` UTC (`created_at`, server default `CURRENT_TIMESTAMP`).

- `vat_code(code TEXT PK, name TEXT NOT NULL, rate_bp INTEGER NOT NULL, is_active BOOL NOT NULL DEFAULT 1)`
- `account(id PK, code TEXT UNIQUE NOT NULL CHECK(length=4 AND numeric), name, rgs_code TEXT NULL, type TEXT CHECK in (...), is_postable BOOL, is_active BOOL, is_system BOOL, default_vat_code TEXT NULL FK vat_code.code)`
- `journal(id PK, code TEXT UNIQUE, name, type TEXT CHECK, account_id FK account NULL, is_active BOOL)`; CHECK `(type IN ('bank','kas')) = (account_id IS NOT NULL)`... SQLite-compatible form: `(type NOT IN ('bank','kas') OR account_id IS NOT NULL)`.
- `fiscal_year(id PK, year INT UNIQUE, start_date, end_date, status TEXT CHECK in ('open','closed'))`
- `period(id PK, fiscal_year_id FK, number INT CHECK 1..12, start_date, end_date, status TEXT CHECK in ('open','locked'), locked_at NULL, UNIQUE(fiscal_year_id, number))`
- `entry_sequence(journal_id FK, fiscal_year_id FK, last_number INT, PK(journal_id, fiscal_year_id))` — only table (besides status columns) that may be updated.
- `journal_entry(id PK, journal_id FK, period_id FK, entry_number TEXT UNIQUE, booking_date DATE, description TEXT, reference TEXT NULL, kind TEXT CHECK in ('normal','opening','storno'), reverses_entry_id FK journal_entry NULL UNIQUE, source_type TEXT NULL, source_id INT NULL, created_at)`; CHECK `(kind='storno') = (reverses_entry_id IS NOT NULL)`; index on `(booking_date)`, `(journal_id, id)`.
- `journal_line(id PK, entry_id FK, line_no INT, account_id FK, debit_cents INT NOT NULL DEFAULT 0, credit_cents INT NOT NULL DEFAULT 0, description TEXT NULL, vat_code TEXT NULL FK vat_code.code, UNIQUE(entry_id, line_no))`; CHECK `debit_cents >= 0 AND credit_cents >= 0 AND ((debit_cents > 0) <> (credit_cents > 0))`; index on `account_id`.

Triggers (created in migration 0002, dropped in downgrade):
- `journal_entry_no_update`, `journal_entry_no_delete`, `journal_line_no_update`, `journal_line_no_delete`: `RAISE(ABORT, 'Boekingen zijn onveranderlijk (append-only)')`.
- `journal_entry_period_open` (BEFORE INSERT on journal_entry): abort if the entry's period is not `open` or `booking_date` is outside the period's range.
- `journal_line_period_open` (BEFORE INSERT on journal_line): abort if the entry's period is locked.
- `period_lock_only` (BEFORE UPDATE on period): abort unless `OLD.status='open' AND NEW.status='locked'` with all other columns unchanged except `locked_at`, or no-op update of identical row; `period_no_delete`.
- `fiscal_year_close_only` (BEFORE UPDATE): only `status` `open -> closed`; `fiscal_year_no_delete`.
- Balance cannot be enforced per-row in SQLite; it is enforced in `post_entry` (single code path, one transaction) and covered by a test that sums the whole ledger after random postings.

### Posting flow (`service.post_entry`)
1. `validate_entry(new_entry)` (pure: shape, amounts, balance, line count, description).
2. Load accounts and VAT codes in one query each; check existence/active/postable.
3. Resolve fiscal year and period for `booking_date`; check open.
4. Within the caller's transaction (`session.begin_nested()` is not needed; service does `session.flush()`, caller/route commits; the service function itself commits only through a helper `ledger_transaction(session)` context manager that wraps `session.begin()`-style semantics so a failed validation leaves no rows and no consumed sequence number): upsert `entry_sequence` row, increment, build `entry_number`, insert entry + lines.
5. Return the ORM entry (with lines loaded).
Decision: service functions flush, they do not commit; the route dependency/handler commits on success and rolls back on exception (a small `commit_or_rollback` helper in `app/db.py` is NOT added; routes call `session.commit()` explicitly). Tests commit explicitly.

### Seed data (builder may adjust names but must keep codes marked * stable because later features depend on them)
Numbering: 0xxx vaste activa, 1xxx vlottend (liquide middelen, vorderingen, voorraad), 2xxx eigen vermogen, 3xxx schulden/belastingen, 4xxx kosten, 8xxx opbrengsten/omzet, 9xxx overig. RGS codes are best-effort from RGS 3.x for ZZP/eenmanszaak (e.g. `BLimBan`, `BVorDeb`, `BSchCre`, `WOmzNed`...); the builder verifies against the public RGS reference where feasible, and any code it cannot verify is left `NULL` with a `# TODO verify` comment in the seed file rather than invented. A test asserts rgs_code is either NULL or matches `^[BW][A-Za-z]+$`.

Assets: 0100 Inventaris, 0110 Computers en apparatuur, 0120 Bedrijfsauto, 0190 Cumulatieve afschrijvingen (system, for later assets feature), 1100* Kas, 1210* Bank, 1220 Spaarrekening, 1230* Kruisposten / nog te boeken, 1300* Debiteuren, 1310 Overige vorderingen, 1320 Vooruitbetaalde kosten, 1400* BTW voorbelasting (te vorderen), 1410* BTW verlegd - voorbelasting, 1500 Voorraad.
Equity: 2000* Ondernemingsvermogen / Kapitaal, 2010* Privé-opnamen, 2020* Privé-stortingen, 2030* Privégebruik / privé-aandeel kosten, 2900* Beginbalans / overboekingsrekening (technical, for opening entries), 2910* Winst/verlies lopend boekjaar (system placeholder, unused until year-end feature).
Liabilities: 3000* Crediteuren, 3100* BTW af te dragen hoog (21%), 3110* BTW af te dragen laag (9%), 3120* BTW af te dragen overig, 3130* BTW verlegd - af te dragen, 3140* BTW privégebruik, 3150* BTW rekening-courant (Belastingdienst), 3200 Af te dragen loonheffing, 3300 Te betalen inkomstenbelasting/ZVW, 3400 Overige schulden, 3500 Vooruitontvangen bedragen, 3600 Lening bank.
Revenue: 8000* Omzet hoog (21%), 8010 Omzet laag (9%), 8020 Omzet 0% / vrijgesteld, 8030 Omzet btw verlegd (binnenland), 8040 Omzet EU (ICP), 8050 Omzet buiten EU (export), 8900 Overige bedrijfsopbrengsten, 8990 Rente-opbrengsten.
Expense: 4000 Inkoopwaarde omzet, 4100 Huur bedrijfsruimte, 4110 Gas, water, elektra, 4200 Kantoorbenodigdheden, 4210 Telefoon en internet, 4220 Software en abonnementen, 4230 Porti en verzendkosten, 4300 Autokosten brandstof, 4310 Autokosten overig, 4320 Reiskosten openbaar vervoer, 4400 Verzekeringen, 4500 Reclame en marketing, 4510 Representatiekosten, 4600 Advies- en accountantskosten, 4610 Administratiekosten, 4700 Opleidingskosten, 4800 Afschrijvingen, 4900 Bankkosten, 4910 Rentelasten, 4950* Kasverschillen, 4960 Overige bedrijfskosten, 4999* Nog te verdelen / suspense kosten.
Headers are omitted: `is_postable` exists for future grouping, all seeded accounts postable.
`default_vat_code` seeded: 8000 `NL_21`, 8010 `NL_9`, 8020 `NL_0`, 8030 `VERLEGD`, 8040 `EU_DIENSTEN`, 8050 `EXPORT`, expense accounts `NL_21` except 4400/4900/4910/4800/4960 (`GEEN`).

### Errors
`LedgerError(Exception)` with `code: str`, `message: str` (Dutch), subclassable. Domain never raises `HTTPException`. Routes map: validation-type errors -> 422 re-render, `PERIOD_LOCKED`/`NO_OPEN_PERIOD`/`ALREADY_REVERSED` -> 409 with message in page, unknown ids -> 404.

### Interfaces fixed between parts
Part A exposes (pure): `NewLine(account_id:int, debit_cents:int=0, credit_cents:int=0, description:str|None=None, vat_code:str|None=None)`, `NewEntry(journal_id:int, booking_date:date, description:str, lines:list[NewLine], reference:str|None=None, kind:str="normal")`, `validate_entry(entry) -> None`, `build_storno(entry_lines, ...) -> list[NewLine]`, `generate_periods(year)`, `period_for_date`. Part C (service) consumes Part A and Part B models and exposes the functions in "Package layout". Part D consumes only `app.domain.ledger` public API and `app.models` for read-only listing queries through service query helpers (`list_entries(session, journal_code=None, page=1, per_page=50) -> Page[EntryRow]`, `get_entry(session, id)`, `list_accounts`, `list_journals`, `list_fiscal_years`) — so Part C must also provide these query helpers.

## Work breakdown
Disjoint file ownership; each part ships its own tests.

- **Part A - pure domain + tests (no DB)**. Owns: `app/domain/money.py`, `app/domain/errors.py`, `app/domain/ledger/entries.py`, `app/domain/ledger/periods.py`, `tests/domain/test_money.py`, `test_entries.py`, `test_periods.py`, `tests/domain/__init__.py` (if needed). Written test-first (tdd skill): money parsing/formatting, line/entry validation, balance, storno builder, period generation (leap year, month ends). No SQLAlchemy imports. No dependencies.
- **Part B - models, migration, seed + DB-level tests**. Owns: `app/models/__init__.py`, `app/models/ledger.py`, `migrations/versions/0002_core_ledger.py`, one-line `import app.models` in `migrations/env.py`, `app/seed/` (`__init__.py`, `rgs_accounts.py`), `tests/test_ledger_schema.py`, and updating `tests/test_migrations.py` expected head to `0002_core_ledger`. Includes trigger tests via raw SQL (update/delete rejected, locked-period inserts rejected, unique storno, CHECK constraints, seed content/uniqueness, `alembic check` clean, downgrade clean). No dependencies (uses table contract above).
- **Part C - ledger service + integration tests**. Owns: `app/domain/ledger/service.py`, `app/domain/ledger/__init__.py`, `tests/ledger/` (conftest with migrated tmp DB session fixture, `test_post_entry.py`, `test_storno.py`, `test_periods_locking.py`, `test_accounts_journals.py`, `test_trial_balance.py`). Depends on A (interfaces) and B (models/migration); may start in parallel against the contract and integrate when B lands. Test-first.
- **Part D - minimal UI**. Owns: `app/web/ledger_routes.py`, `app/web/templates/ledger/*`, additions to `app/web/static/app.css` (appended section, no edits to existing rules), `euro` filter registration and including the new router in `app/web/__init__.py` / `app/web/routes.py` (the ledger router must be registered before the placeholder routes so `/boeken` and `/instellingen` stop being placeholders; drop the placeholder registration for those two keys), `tests/test_ledger_web.py`. Depends on C (can stub against signatures; integrates last). Not allowed to touch other parts' files.

Integration points: table/column names (A->B->C), `LedgerError` codes (A->C->D), service signatures (C->D), Alembic head revision id `0002_core_ledger` (B), `migrations/env.py` import (B). The orchestrating step merges A, B, C, D in that order and runs the whole suite.

## Test strategy
Tests first for everything touching money (tdd skill): Part A and C are red-green.
- Unit (A): parse/format euro round trips and rejections; floats refused; unbalanced by 1 cent; zero lines; both-sided line; storno builder swaps sides and preserves total; periods for 2024 (leap) and 2025.
- Schema (B): every trigger and CHECK exercised with raw SQL; seed has unique codes, required system codes (1300, 3000, 3100, 3110, 3120, 3130, 1400, 1410, 3150, 2000, 2010, 2020, 8000), five journals, eight VAT codes, bank/kas journals point to asset accounts; migration up/down/check.
- Integration (C): post and read back; gapless numbering per (journal, year) including after a rejected post; numbering restarts per year/journal; lock then post -> `PERIOD_LOCKED`; storno happy path, double storno, storno of storno, storno into locked period with explicit open date; trial balance always balanced after a mixed series; inactive account rejected; unknown VAT code rejected; delete used account rejected; close year locks all periods.
- Web (D): TestClient with migrated tmp DB: list renders, create entry happy path (Dutch amounts), unbalanced -> 422 with message "niet in evenwicht"-style Dutch text, storno flow, lock period then posting fails with 409 message, settings pages render, `/instellingen` redirect and nav active state, no `data/boekhouden.db` access.

## Risks and decisions made
- **Boekjaar = calendar year, periods = months** (eenmanszaak/VOF files IB on calendar year; BTW quarters are aggregations of monthly periods later). Broken fiscal years are out of scope.
- **Locking is permanent** in this feature (CLAUDE.md: closed periods locked; corrections go into an open period via storno with a current date). A BTW-filing lock later uses the same `lock_period`. If an unlock ever proves necessary it needs an explicit, audited feature.
- **No drafts**: simplifies append-only; a half-filled form is simply not submitted.
- **Entry number format** `{DAGBOEK}-{JAAR}-{NNNN}` per dagboek per boekjaar gives gapless, human-friendly boekstuknummers; sales invoice numbering (art. 35a) is a separate concern for the invoice feature, which can reuse `entry_sequence` patterns.
- **Immutability enforced in the database with triggers** (not just the API) because the DB is a single local file others tools could touch; cost: Alembic `check` can't see triggers (acceptable), and migrations must create/drop them explicitly. Test-data cleanup in tests uses fresh tmp DBs, never DELETE.
- **Balance enforced in code, not DB** (SQLite cannot defer a cross-row constraint cheaply); single posting code path plus a ledger-wide balance test mitigates it.
- **Services flush, routes commit**: keeps one transaction per request and makes rollback of a failed post (incl. sequence number) trivial.
- **Storno date**: defaults to the original date, falling back to today when that period is locked, so storno never silently posts into a closed period.
- **RGS codes best-effort**: the seed is a pragmatic subset keyed by our own 4-digit codes; `rgs_code` is a reference for later RGS-based reports/export, unverifiable codes stay NULL rather than guessed.
- **VAT code on lines, no rubriek mapping yet**: rubriek derivation will map (vat_code, account type/side) to rubrieken in the BTW feature, which may add columns via migration.
- Money in Python is `int` throughout; `bool` is rejected explicitly since `bool` is an `int` subclass.
- Risk: SQLite `BEFORE UPDATE` triggers and Alembic batch mode (`render_as_batch=True`) can recreate tables and drop triggers on later migrations touching these tables; later migrations on ledger tables must recreate the triggers (note left in migration docstring).
