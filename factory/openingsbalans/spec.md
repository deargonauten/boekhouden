Status: APPROVED

# Spec: openingsbalans (beginstanden invoeren bij start, feature 36)

## 1. Goal and context
A business that starts using Boekhouden mid-life already has money in the bank, a car, unpaid customer invoices, unpaid supplier invoices, BTW still to pay, a loan. The owner enters these starting amounts once ("Waarmee begin je?") and the program books them as **one balanced journal entry** (kind `opening`) on the first day of the first boekjaar in the memoriaal. Unpaid invoices are entered per invoice (openstaande posten) so later features (bank reconciliation, sales invoices) can match payments against them, and unpaid supplier invoices show up on `/inkoop`.

Builds on existing code:
- Ledger: `post_entry` / `reverse_entry` (`app/domain/ledger/service.py`); `NewEntry(kind="opening")` is already allowed and already restricted to a journal of type `memoriaal`; `validate_entry`, savepoint numbering, `_find_period` locked/no-year messages; `default_journal_id(session, "memoriaal")` (`suggestions.py`); `JournalEntry.source_type/source_id`.
- Seeded accounts: `1300 Debiteuren`, `3000 Crediteuren`, `2000 Ondernemingsvermogen / Kapitaal` (all system); balance accounts are type `asset` / `liability` / `equity`. Journal `MEM` (memoriaal).
- Relations (`Contact`, `is_customer`, `is_supplier`), purchase overview `open_by_supplier` (`app/domain/purchase/service.py`), glossary (`app/domain/glossary.py`), settings nav (`ledger/_settings_nav.html`).

## 2. Non-goals
- Opening balance of a later boekjaar: that comes from the year-end closing (future jaarafsluiting feature). Only the **first** boekjaar in the system gets a beginbalans.
- Open creditnota's as openstaande post (amount must be > 0). Workaround in helper text: subtract it from another open invoice of the same relation.
- Per-vennoot capital split for a VOF (everything goes to `2000`), foreign currency, BTW on opening lines, importing a balance from a file/previous package, paying/matching opening posten (later reconciliation feature fills `paid_cents`).
- Showing opening posten in the "Alle inkoopfacturen" list (only in totals per leverancier and a separate block, see AC 15).

## 3. User stories
- As owner starting with the program I fill in, in plain Dutch, what my business owns and owes on the start date; the program computes my eigen vermogen and books it so everything balances, without me knowing debet/credit.
- As owner I enter my unpaid customer and supplier invoices one by one (relation, factuurnummer, datum, bedrag), so I can later see when they are paid.
- As owner I can correct my beginbalans later (while the first period is still open); the program does it with a storno + new booking, never by editing.
- As owner I see the open supplier invoices from my beginbalans on "Inkoop".

## 4. Acceptance criteria

### Domain rules
1. **Target boekjaar**: the earliest `FiscalYear` in the system. Booking date = its `start_date`. If no boekjaar exists: "Maak eerst je eerste boekjaar aan onder Instellingen > Boekjaren." (with link). A beginbalans for any other year is refused: "De beginbalans van <jaar> volgt uit het boekjaar ervoor. Alleen je eerste boekjaar (<eerste jaar>) krijgt een beginbalans."
2. **Input** (`OpeningInput`): `balances: list[(account_id, amount_cents)]` and `items: list[OpeningItemInput(side 'debiteur'|'crediteur', contact_id, invoice_number, invoice_date, due_date|None, amount_cents)]`. All amounts integer cents (parsed with `app.domain.money`).
3. **Allowed balance accounts**: active, postable accounts of type `asset` or `liability`, excluding `1300` and `3000` (these are derived from the openstaande posten) and excluding all `equity` accounts (eigen vermogen is computed, AC 5). Amount 0 / empty = skip. A negative amount is allowed (e.g. bank rood staan, `0190` cumulatieve afschrijvingen); helper text says so. Other account -> "Rekening <code> <naam> hoort niet in de beginbalans. Kies een rekening voor bezittingen of schulden."
4. **Lines** (no `vat_code` on any line, so the BTW-aangifte is unaffected):
   - asset account: amount > 0 -> DEBIT amount; < 0 -> CREDIT |amount|.
   - liability account: amount > 0 -> CREDIT amount; < 0 -> DEBIT |amount|.
   - each debiteur post -> DEBIT `1300` amount, description "<relatie> - <factuurnummer>".
   - each crediteur post -> CREDIT `3000` amount, description "<relatie> - <factuurnummer>".
   - **eigen vermogen** = sum(debits) - sum(credits) of the lines above; if > 0 one CREDIT line on `2000` for that amount, if < 0 one DEBIT line on `2000` for |amount| (negative vermogen allowed, shown with a plain warning "Je schulden zijn hoger dan je bezittingen; je eigen vermogen is negatief. Klopt dat?"), if 0 no line.
   The entry balances by construction and passes `validate_entry`. Nothing filled in at all -> "Vul minstens één bedrag of openstaande factuur in." A result with fewer than 2 lines cannot occur once any amount is non-zero (vermogen line is added).
5. **Entry fields**: journal = `default_journal_id(session, "memoriaal")` (none -> "Er is geen memoriaal actief. Zet het memoriaal aan onder Instellingen > Dagboeken."); `kind="opening"`; `booking_date` = boekjaar start; `description="Beginbalans <jaar>"`; `reference=None`; `source_type="beginbalans"`, `source_id=fiscal_year.id`.
6. **Openstaande posten validation** (plain-Dutch, naming the row "Openstaande factuur 2: ..."): contact exists and is active; `invoice_number` non-empty (trimmed, max 64); `invoice_date` set and on or before the start date ("De factuurdatum ligt na de startdatum van je administratie. Boek deze factuur gewoon via de Inbox of Verkoop."); `due_date` optional, not before `invoice_date`; `amount_cents > 0` ("Vul een bedrag groter dan nul in. Een openstaande creditnota trek je af van een andere factuur van dezelfde relatie."); no duplicate (side, contact, lower/trim number) within the form ("Factuur <nr> van <naam> staat er twee keer in."). Contact role flags are not required; when a debiteur post uses a contact without `is_customer` (or crediteur without `is_supplier`), the flag is set on booking (no question to the user).
7. **One active beginbalans**: at most one non-storno'd `opening` entry with `source_type="beginbalans"` per boekjaar. `book_opening_balance` when one already exists -> treated as **aanpassen** (AC 8), never a second one.
8. **Aanpassen (correct)**: in one transaction: `reverse_entry(old_entry_id, booking_date=start_date, description="Storno beginbalans <jaar> (aangepast)")`, then post the new opening entry and new `opening_item` rows. The old items stay (append-only) and are derived as "vervangen" because their entry is reversed. Refused when: the first period is locked/closed (existing `PERIOD_LOCKED` ledger message, nothing changes), or any old item has `paid_cents > 0` ("Factuur <nr> uit je beginbalans is al (deels) betaald. Pas de beginbalans aan met een gewone boeking in het memoriaal."). If the new input is identical to the active one: no-op, message "Er is niets veranderd."
9. **Atomic**: storno (if any), entry, items, contact flag updates commit together or not at all; on any error nothing persists and no entry number is consumed (existing savepoint behaviour; service flushes, caller commits).
10. **Read model** `get_opening_balance(session) -> OpeningView | None`: boekjaar, entry (number, id), balance rows (account code/name, signed amount), item rows (side, relation, number, dates, amount, open amount, status open|betaald|vervangen), totals: bezittingen, schulden, eigen vermogen. Used to prefill the form for aanpassen.
11. **Trial balance**: after booking, `trial_balance` for the start date shows each entered account with its amount, `1300` = sum debiteur posten, `3000` = sum crediteur posten, `2000` = computed vermogen; total debit = total credit (test).

### Crediteuren integration
12. `open_by_supplier` includes open crediteur opening items (entry not reversed, `amount_cents - paid_cents > 0`) in the per-leverancier counts/amounts and in the totals; `SupplierOpenRow` gets `opening_count: int = 0`. AC 16 of purchase-booking-flow (3000 balance = total open) keeps holding with opening posten included (test).
13. `list_opening_items(session, side, open_only=True) -> list[OpeningItemRow]` for screens.

### Web / UX (`/instellingen/beginbalans`)
14. New settings tab "Beginbalans" in `ledger/_settings_nav.html`. Page title "Waarmee begin je? (beginbalans)". Shows start date and boekjaar, then three cards:
   - **"Wat heb je?" (bezittingen / activa)**: one amount input per allowed asset account (code + name), prefilled with current values when a beginbalans exists. Helper: "Saldo op <startdatum>, zoals op je bankafschrift of vorige jaarrekening."
   - **"Wat moet je nog betalen?" (schulden / passiva)**: one input per allowed liability account.
   - **"Openstaande facturen"**: two sub-tables "Klanten die jou nog moeten betalen (debiteuren)" and "Leveranciers die jij nog moet betalen (crediteuren)", rows: relatie (select of active contacts, customers resp. suppliers listed first), factuurnummer, factuurdatum, vervaldatum, bedrag; "Regel toevoegen" via HTMX (`GET /instellingen/beginbalans/regel?side=...`), like `/boeken/nieuw/regel`. Link "Nieuwe relatie" opens `/relaties` in a new tab.
   - **Summary** (updated via HTMX `POST /instellingen/beginbalans/controle` on input change, server-side computation with the domain function, no JS money math): totaal bezittingen, totaal schulden, "Eigen vermogen (berekend)" = verschil, plus the negative-vermogen warning.
   - Button "Beginbalans boeken" (or "Beginbalans aanpassen" when one exists; then the button text explains: "We maken de oude boeking ongedaan (storno) en boeken de nieuwe.").
15. `/inkoop` shows, when open crediteur opening items exist, a block "Nog te betalen uit je beginbalans" (leverancier, factuurnummer, factuurdatum, vervaldatum with "te laat" pill, bedrag) under the per-leverancier tab; per-leverancier rows with `opening_count` show "waarvan <n> uit beginbalans".
16. `POST /instellingen/beginbalans` books and redirects to `/instellingen/beginbalans?melding=geboekt` with a success notice linking to the boeking (`/boeken/{id}`). Errors: status 422, `error_box`, all entered values and rows kept.
17. When a beginbalans exists, the page shows its boeking number + link and the item status pills; when the first period is locked the form is read-only with the note "Je eerste periode is vergrendeld; de beginbalans kan niet meer worden aangepast."
18. Entry detail (`ledger/_entry_detail_body.html`) for `source_type="beginbalans"` links "Bekijk beginbalans" to the page.
19. If no boekjaar exists, the page shows only the plain message of AC 1 with a link to Boekjaren. Mobile: cards/tables stack at phone width (existing components).

### Plain-language (CLAUDE.md global requirement)
New glossary terms in `app/domain/glossary.py` (info icon on screen):
- `beginbalans` ("Beginbalans" / plain "Waarmee je begint"; what you own and owe on the first day, booked once in the memoriaal). Detect pattern must not match the seeded account name "Beginbalans / overboekingsrekening" on the grootboek screen: use `detect=(r"\bbeginbalans\b(?!\s*/)",)`.
- `openstaande_post` ("Openstaande post" / plain "Factuur die nog niet betaald is"; entered per factuur so payments can be matched later).
- `beginbalans_aanpassen` ("Beginbalans aanpassen" / plain "Je beginstanden verbeteren"; explains storno of the old booking + new booking, only while the first period is open).
- `eigen_vermogen_berekend` ("Eigen vermogen (berekend)" / plain "Wat er overblijft als je alles verkoopt en je schulden betaalt"; bezittingen min schulden, the program fills it in).
Reused: `activa`, `passiva`, `eigen_vermogen`, `debiteuren`, `crediteuren`, `memoriaal`, `storno`, `boekjaar`, `periode`, `vergrendelen`, `boeking`, `openstaand`.
Suggested defaults: boekjaar = first boekjaar, date = its start date, dagboek = memoriaal, eigen vermogen computed, empty amounts = 0, accounts pre-listed (no choosing from the full RGS). Plain-Dutch errors: AC 1, 3, 4, 5, 6, 8; ledger messages reused for locked period. `tests/test_plain_language.py` must pass with the new page included in its page list.

## 5. Technical approach

### Data model (Alembic `migrations/versions/0010_opening_balance.py`, model in `app/models/opening.py`, exported from `app/models/__init__.py`)
`opening_item`: `id`, `fiscal_year_id` FK fiscal_year NOT NULL, `journal_entry_id` FK journal_entry NOT NULL, `contact_id` FK contact NOT NULL, `side` CHECK in ('debiteur','crediteur'), `invoice_number` str NOT NULL, `invoice_number_key` str NOT NULL, `invoice_date` date NOT NULL, `due_date` date NULL, `amount_cents` int NOT NULL CHECK > 0, `paid_cents` int NOT NULL default 0 CHECK `paid_cents >= 0 AND paid_cents <= amount_cents`, `created_at`. Indexes: `contact_id`, `journal_entry_id`. Never deleted or updated (except `paid_cents` by future reconciliation). Balance amounts need no table: they are the entry lines (the read model reconstructs them from the active entry's lines, excluding 1300/3000/2000).

### Domain (`app/domain/opening/`; no logic in routes)
- `build.py` (pure, no DB): dataclasses `OpeningInput`, `OpeningItemInput`, `AccountRef(id, code, name, type)`, `OpeningSummary(assets_cents, liabilities_cents, equity_cents, warnings)`; `check_input(input, allowed: dict[int, AccountRef], start_date) -> None` (raises `OpeningError`), `summarize(input, allowed) -> OpeningSummary`, `build_entry(input, allowed, system: SystemIds(debtors, creditors, equity), journal_id, year, start_date, contact_names) -> NewEntry`.
- `errors.py`: `OpeningError(LedgerError)` with codes `NO_FISCAL_YEAR`, `NOT_FIRST_YEAR`, `NO_JOURNAL`, `ACCOUNT_NOT_ALLOWED`, `EMPTY`, `INVALID_ITEM`, `DUPLICATE_ITEM`, `ITEM_PAID`, `UNCHANGED`.
- `service.py`: `first_fiscal_year(session)`, `allowed_accounts(session) -> list[AccountRef]` (ordered by code, grouped asset/liability), `get_opening_balance(session) -> OpeningView | None`, `preview(session, input) -> OpeningSummary` (for the HTMX summary; never raises for incomplete rows, returns warnings), `book_opening_balance(session, input) -> JournalEntry` (AC 1-9; uses `post_entry`, `reverse_entry`, sets `source_type/source_id`, inserts items, sets contact flags), `list_opening_items(session, side, open_only=True)`.
- `purchase/service.py`: `open_by_supplier` merges open crediteur opening items (AC 12) via `list_opening_items`.
Errors: every domain failure is a `LedgerError` subclass with a Dutch `message`; routes show `message` only.

### Web
`app/web/opening_routes.py` (`router`): `GET/POST /instellingen/beginbalans`, `GET /instellingen/beginbalans/regel`, `POST /instellingen/beginbalans/controle`. Form parsing: amounts via `app.domain.money.parse_euro` (as `/boeken/nieuw`); invalid amount -> "Vul bij <rekening> een geldig bedrag in, bijvoorbeeld 1.250,00." Registered in `app/web/routes.py`.

## 6. Work breakdown (2 builders, disjoint files)

**Builder A - domain + data (tests first; critical path)**
Owns: `app/models/opening.py`, `app/models/__init__.py`, `migrations/versions/0010_opening_balance.py`, `app/domain/opening/**`, `app/domain/purchase/service.py` (only `open_by_supplier` + `SupplierOpenRow.opening_count`), `tests/opening/**` (pure, service, migration), addition to `tests/purchase/` for AC 12.
Delivers the signatures in section 5 early (dataclasses first) so B can build against them.

**Builder B - screens, glossary, wiring**
Owns: `app/web/opening_routes.py`, `app/web/routes.py`, `app/web/templates/opening/**`, `app/web/templates/ledger/_settings_nav.html`, `app/web/templates/ledger/_entry_detail_body.html`, `app/web/templates/purchase/**` (AC 15 block), CSS if needed (`app/web/static/css/opening.css`), `app/domain/glossary.py` (terms of section 4), `tests/test_opening_web.py`, `tests/test_plain_language.py` (add the page).
Depends on A's `allowed_accounts`, `get_opening_balance`, `preview`, `book_opening_balance`, `list_opening_items`, `OpeningInput`/`OpeningItemInput`, `SupplierOpenRow.opening_count`.

Integration: A merges first; B's only shared touchpoint is `SupplierOpenRow.opening_count` in templates.

## 7. Test strategy (tests first for money)
- Pure: sign rules asset/liability positive/negative, debiteur/crediteur lines, vermogen credit/debit/none, balance by construction, no vat_code on any line, every validation message (empty, account not allowed incl. 1300/3000/equity, item date after start, due before invoice date, amount <= 0, duplicate item, number too long).
- Service (SQLite fixture as in `tests/ledger`): happy path entry kind `opening` in MEM on start date with `source_type/source_id`, items stored, contact flags set; no boekjaar / not first year / no memoriaal errors; locked first period -> nothing persisted, sequence not consumed; aanpassen = storno + new entry, old items derived "vervangen", only one active; identical input -> UNCHANGED; paid item blocks aanpassen; trial balance (AC 11); `open_by_supplier` includes opening posten and 3000 balance equals total open.
- Migration: upgrade/downgrade 0010, CHECK constraints.
- Web: page renders plain-Dutch cards and info icons, empty-boekjaar state, add-row partial, controle summary, POST books and redirects with notice, 422 keeps values, aanpassen flow, read-only when locked, `/inkoop` block, entry detail link; plain-language test passes. Run the full suite once at the end.

## 8. Risks and decisions
- Decision: eigen vermogen is computed (bezittingen - schulden) and booked on `2000`; the user never balances anything by hand, so the "Debet = credit" error cannot occur from this screen.
- Decision: only the first boekjaar gets a beginbalans; later years follow from jaarafsluiting (avoids two sources of truth).
- Decision: correction = storno + new entry in one transaction (append-only), only while period 1 is open; existing ledger locking does the enforcement.
- Decision: openstaande posten per factuur in a separate `opening_item` table (not `purchase_invoice`, which requires a document and one entry per invoice); `paid_cents` prepared for the reconciliation feature, status derived at read time like purchase invoices.
- Decision: no BTW codes on opening lines; open BTW from the previous period is entered as a balance on `3150`/`1400` etc.
- Decision: contact role flags set automatically rather than asking.
- Risk: a later inkoop booking of an invoice that is also an opening post double-counts; mitigated by helper text ("Facturen van vóór de startdatum die nog open staan: alleen hier invullen, niet in de Inbox boeken"). A cross-check can be added with reconciliation.
- Risk: glossary detect for "beginbalans" vs the seeded account name; handled by the pattern in section 4.
