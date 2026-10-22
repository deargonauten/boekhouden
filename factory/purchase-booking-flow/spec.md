Status: APPROVED

# Spec: purchase-booking-flow (inkoopfactuur boeken)

## 1. Goal and context
Turn a reviewed ("nagekeken") extracted invoice into a real booking. The owner presses "Goedkeuren en boeken" on the review screen (`/inbox/{id}/nakijken`) and the system, in one transaction:
1. posts a balanced journal entry in the inkoopdagboek (IK),
2. creates an `inkoopfactuur` record (purchase invoice) linked to the supplier (relation), the document and the entry,
3. marks the document `geboekt` (linked to the entry),
4. remembers the chosen grootboekrekening + btw-code per supplier (learned defaults),
and the new screen `/inkoop` (Crediteuren) shows what is still to be paid, per leverancier.

Builds on: document inbox (`Document`, `mark_booked`), extraction + review (`InvoiceExtraction(+Line)`, `save_review`, `suggestions.py`), relations (`Contact`), core ledger (`post_entry`, `reverse_entry`, periods/locking, `default_journal_id`), grootboek-verfijning (`Account.default_vat_code`, `VatCode.purchase_rubriek`), glossary, bedrijfsgegevens (not needed beyond existing).

Seeded accounts used: `3000 Crediteuren`, `1400 BTW voorbelasting (te vorderen)`; expense accounts per line (type `expense`). Journal: first active journal of type `inkoop` (`IK`).

## 2. Non-goals
- Payments / bank matching / marking invoices paid (later features: bank import, reconciliation). The data model carries `paid_cents` (always 0 now) so those can add to it.
- Verlegde BTW, EU-intracommunautair, import/export purchases (codes `VERLEGD`, `EU_GOEDEREN`, `EU_DIENSTEN`, `EXPORT`): booking is refused with a plain message; handled with the BTW-aangifte feature.
- Foreign currency (only `EUR`).
- Re-opening a booked document. A wrong booking is fixed by a stornoboeking (existing ledger screen); the document stays `geboekt` and linked. Re-booking the same file is out of scope (user adds a manual boeking in the memoriaal).
- Editing a booked invoice; sales invoices; BTW-aangifte; reports.

## 3. User stories
- As owner I review an extracted invoice, see a plain-Dutch preview of what will be booked ("Kosten €100,00, BTW €21,00, nog te betalen aan Leverancier €121,00") and confirm in one click.
- As owner I get the rekening and btw-code pre-filled from what I chose last time for this supplier, so repeat invoices need only a glance.
- As owner I see on "Inkoop" which suppliers I still owe money and which invoices are open, with link to document and boeking.
- As owner I am stopped with a clear message when the invoice cannot be booked (missing field, locked period, duplicate, unsupported btw-code).

## 4. Acceptance criteria

### Booking rules (domain)
1. Booking is allowed only if: extraction `status='ok'` and `reviewed_at` is set; document status is not `geboekt`; `contact_id` set; `invoice_date` set; `invoice_number` set; currency `EUR`; at least one line; every line has `account_id`, `vat_code`, and `amount_excl_cents` and `vat_amount_cents` (ints); totals consistent: sum(lines excl) = `total_excl_cents`, sum(lines vat) = `total_vat_cents`, excl + vat = `total_incl_cents`; `total_incl_cents > 0`. Each failure raises a plain-Dutch `BookingError` naming the field and what to do (e.g. "Kies bij regel 2 een rekening voor de kosten.").
2. VAT codes with a purchase rubriek other than `5b`/none (i.e. `VERLEGD`, `EU_*`, `EXPORT`) are refused: "Deze factuur heeft verlegde of buitenlandse BTW. Dat boeken we hier nog niet automatisch; leg het vast met een handmatige boeking."
3. Entry for `kind='invoice'` (all integer cents): per extraction line one DEBIT line on the line's expense account for `amount_excl_cents` carrying the line's `vat_code` (grondslag; the voorbelasting line carries no vat_code, so the BTW feature sums the grondslag per code); one DEBIT line on `1400` per distinct vat code with total vat > 0 (sum of printed vat amounts, not recomputed); one CREDIT line on `3000 Crediteuren` for `total_incl_cents`. Entry balances by construction and passes `validate_entry`. Lines with 0 amount excl are not allowed (ledger rule) and give a plain error.
4. `kind='credit_note'`: same lines with debit/credit swapped (credit expense + credit 1400, debit 3000); amounts stay positive as extracted.
5. Entry fields: journal = default inkoop journal (error "Er is geen inkoopdagboek actief" if none); `booking_date = invoice_date`; `reference = invoice_number`; `description = "<leveranciersnaam> - <factuurnummer>"` (truncated to 255); `source_type='inkoopfactuur'`, `source_id` = purchase invoice id (set after insert, within same transaction).
6. If `invoice_date` falls in a locked period / no open period, the ledger error is surfaced as the existing plain-Dutch ledger message. The date is never changed silently. Nothing is persisted.
7. Duplicate guard: same `contact_id` + `invoice_number` (case-insensitive, trimmed) among non-storno'd purchase invoices is refused: "Deze factuur van <naam> met nummer <nr> is al geboekt." (unique partial index plus pre-check). Storno'd invoice numbers may be booked again.
8. Atomic: entry, purchase invoice, document status/link, learned defaults all commit together or not at all; the entry number sequence is not consumed on failure (existing savepoint behaviour).
9. Booking an already `geboekt` document returns the plain error "Dit document is al geboekt" (no second entry); double-submit safe.
10. The document-entry link: `document.journal_entry_id` = entry id and `purchase_invoice.document_id` unique; entry detail screen shows link back to the document/inkoopfactuur (via `source_type`/document lookup).

### Learned supplier defaults
11. On every successful booking, for each line store/update `supplier_default(contact_id, account_id, vat_code, use_count, last_used_at)` as the most recent choice (one row per contact+account; the "suggestion" for a supplier is: the account with the highest `use_count`, ties by most recent; its vat_code is the last vat_code used with that account for this supplier).
12. Suggestion order for a line without account (applied in extraction `store_result` and when opening the review for lines still empty, never overriding the owner's or the AI's valid choice if the supplier has no history): learned supplier default > AI suggestion > none. Precisely: when the extraction resolves a `contact_id` and the supplier has history, a line without `account_id` gets the learned account and vat_code (vat_code only if the line has none or inferred); lines the AI already filled keep the AI value but show the hint "Vorige keer koos je <rekening> voor deze leverancier" with the learned account. A learned account that is inactive/non-postable is ignored. Learned vat_code falls back to `Account.default_vat_code` when inactive.
13. Learned defaults are suggestions only: the owner always confirms on the review/preview screen.

### Crediteuren (`/inkoop`)
14. `/inkoop` (replaces placeholder; nav item "Inkoop", term crediteuren) shows: stat cards (Totaal openstaand, Aantal open facturen, Leveranciers met openstaand), tab "Openstaand per leverancier" (supplier, # facturen, bedrag) and tab "Alle inkoopfacturen" (datum, leverancier, factuurnummer, totaal, openstaand, vervaldatum with "te laat" pill if past due and open, link to boeking and document). Search on leverancier/factuurnummer; pagination like other lists.
15. Open amount = `total_incl_cents - paid_cents` for credit notes shown as negative (credit note reduces what is owed); invoices whose entry has been reversed (a storno entry with `reverses_entry_id` = entry.id exists) are shown as "Gestorneerd" and excluded from totals. Status is derived at read time (no sync hook into the ledger).
16. Account `3000` balance in trial balance equals the sum of open (non-storno'd) invoice totals (test).
17. Empty state in plain Dutch with link to Inbox.

### Web / UX
18. Review page gets a primary button "Goedkeuren en boeken" (shown only when extraction status ok and document not geboekt) next to "Klaar met nakijken". It links to a preview page `GET /inbox/{id}/boeken` that first saves nothing and shows: leverancier, factuurnummer, datum, "Zo wordt het geboekt" table in plain Dutch (omschrijving, rekening with grootboek term in the info icon, BTW-code + rate, bedrag), the amount still to pay, and the dagboek/periode it lands in; then `POST /inbox/{id}/boeken` books and redirects to `/inkoop?melding=geboekt` (success notice with link to the boeking). If the extraction is not yet nagekeken, the preview says "Eerst nakijken" with link back, button disabled.
19. Errors render on the preview page via `error_box`, status 422, values kept. Missing items link to the review field. Document 404 -> standard 404.
20. Inbox list/detail: `geboekt` documents link to their boeking and inkoopfactuur; no re-extract/re-review actions (already enforced by extraction service `_editable_document`).
21. Mobile: new pages use existing card/table components and work at phone width.

### Plain-language (CLAUDE.md global requirement)
Terms introduced/used, each with a glossary entry in `app/domain/glossary.py` (central, with `detect` patterns where the term is generic) and an info icon on screen:
- `inkoopfactuur` ("Inkoopfactuur" / plain: "Factuur van een leverancier"),
- `goedkeuren_boeken` ("Boeken" / plain: "Vastleggen in je administratie"; explains that after booking it is only fixable via stornoboeking),
- `openstaand` ("Openstaand" / plain: "Nog te betalen"),
- `voorbelasting` ("Voorbelasting" / plain: "BTW die je terugkrijgt" - explains rekening 1400 and that it is the BTW on purchases you can deduct),
- `leerfunctie` (plain: "Onthouden per leverancier"; explains the program remembers your last choice per supplier, always confirmable),
- existing reused: `crediteuren`, `inkoopdagboek`, `storno`, `grootrekening`, `btw_tarief`, `creditnota`, `nakijken`.
Suggested defaults: dagboek (IK), period (from factuurdatum), rekening + btw-code (learned > AI > account default). Plain-Dutch error examples are in AC 1, 2, 6, 7, 9; the unbalanced case reuses the ledger message ("Debet en credit zijn niet gelijk: er ontbreekt €12,10 ..."). `tests/test_plain_language.py` must keep passing (every term on screens has a glossary entry/info icon).

## 5. Technical approach

### Data model (Alembic `0008_purchase_booking.py`, models in `app/models/purchase.py`, exported from `app/models/__init__.py`)
`purchase_invoice`: `id`, `document_id` FK document UNIQUE NOT NULL, `contact_id` FK contact NOT NULL, `journal_entry_id` FK journal_entry UNIQUE NOT NULL, `invoice_number` str NOT NULL, `invoice_number_key` str NOT NULL (lower/trim), `invoice_date` date NOT NULL, `due_date` date NULL, `kind` CHECK in ('invoice','credit_note'), `total_excl_cents`, `total_vat_cents`, `total_incl_cents` int NOT NULL (CHECK > 0), `paid_cents` int NOT NULL default 0 (CHECK >= 0), `created_at`. Indexes on `contact_id`, `invoice_date`. Duplicate guard: pre-check in service (needs storno awareness, so no DB unique on number).
`supplier_default`: `id`, `contact_id` FK, `account_id` FK, `vat_code` FK vat_code NULL, `use_count` int default 1, `last_used_at` datetime; UNIQUE(contact_id, account_id).
Money columns are integer cents. Never delete rows.

### Domain (`app/domain/purchase/`; no logic in routes)
- `booking.py` (pure, no DB): dataclasses `BookingLineInput`, `BookingInput`; `check_bookable(input) -> None` (raises `BookingError(code, message)`), `build_entry(input, accounts: AccountIds{creditors, vat_receivable}, journal_id) -> NewEntry`, `preview_lines(...)` (rows for the preview screen incl. plain Dutch summary text). Uses `app.domain.money`, `ledger.entries.NewEntry/NewLine`. `BookingError` subclass of `LedgerError` in `app/domain/errors.py`-style (own module `purchase/errors.py` to avoid touching shared files; codes e.g. `NOT_REVIEWED`, `MISSING_FIELD`, `DUPLICATE_INVOICE`, `UNSUPPORTED_VAT`, `ALREADY_BOOKED`, `NO_JOURNAL`).
- `service.py`: `book_extraction(session, document_id) -> PurchaseInvoice` (loads extraction/doc, runs checks, posts via `ledger.service.post_entry`, inserts invoice, sets `entry.source_type/source_id`, `documents.service.mark_booked`, `learned.record_booking`); `prepare_booking(session, document_id) -> BookingPreview`; `list_invoices(session, q, tab, page)`, `open_by_supplier(session)`, `invoice_status(...)`.
- `learned.py`: `record_booking(session, contact_id, lines)`, `suggest_for_contact(session, contact_id) -> SupplierSuggestion | None`, `apply_to_lines(session, extraction)` used by extraction service.
- Hook in `app/domain/extraction/service.py` (`store_result` and `save_review` line rows): call `learned.apply_to_lines` per rule AC 12 (small, isolated change).
- Compose with `suggestions.resolve_vat_code_for_account` (already exists) for the account-default fallback.

### Web
- `app/web/booking_routes.py`: `GET/POST /inbox/{id:int}/boeken`; thin handlers calling `prepare_booking`/`book_extraction`, catch `LedgerError` -> 422 re-render.
- `app/web/purchase_routes.py`: `GET /inkoop` (+ htmx partial for search/pagination like other lists).
- `app/web/routes.py`: include both routers before the placeholder loop; add `"inkoop"` to `LEDGER_KEYS`-style skip set.
- Templates: `inbox/book.html` (preview), `purchase/list.html`, `purchase/_rows.html`; small edits in `inbox/review.html`, `inbox/_detail_body.html`, `inbox/_results.html`, `ledger/_entry_detail_body.html` (link back to document/invoice).

### Error handling
All failures are `LedgerError`/`BookingError` with Dutch `message`; routes render `message` only, never codes/tracebacks. DB integrity errors (race on unique) are mapped to the duplicate/already-booked message.

## 6. Work breakdown (3 builders, disjoint files)

**Builder A - domain + data (critical path; others stub against its interfaces defined above)**
Owns: `app/models/purchase.py`, `app/models/__init__.py`, `migrations/versions/0008_purchase_booking.py`, `app/domain/purchase/**`, `app/domain/extraction/service.py` (learned-default hook only), `tests/purchase/**` (domain + migration + learned + extraction hook tests, written first).
Delivers the functions/signatures listed in section 5.

**Builder B - booking UX on the inbox**
Owns: `app/web/booking_routes.py`, `app/web/templates/inbox/book.html`, edits to `inbox/review.html`, `inbox/_detail_body.html`, `inbox/_results.html`, `inbox/_review_line.html` (learned hint), `ledger/_entry_detail_body.html`, `app/web/static/css/inbox.css`, `tests/test_booking_web.py`.
Depends on A's `prepare_booking`/`book_extraction`/`suggest_for_contact` (agree on dataclass `BookingPreview`: `rows`, `supplier_name`, `invoice_number`, `invoice_date`, `total_incl_cents`, `journal_code`, `period_label`, `warnings`).

**Builder C - Crediteuren screen, glossary, wiring**
Owns: `app/web/purchase_routes.py`, `app/web/routes.py`, `app/web/templates/purchase/**`, `app/web/static/css/purchase.css`, `app/domain/glossary.py` (all new terms listed in section 4, with the exact keys), `app/web/navigation.py` (only if label/term changes), `tests/test_purchase_web.py`, glossary/plain-language test additions.
Depends on A's `list_invoices`/`open_by_supplier`. C registers B's router in `routes.py` (`from app.web.booking_routes import router as booking_router`) - integration point; B must export `router`.

Integration order: A merges first (or A publishes signatures + models early), then B and C. Shared-file risk: only `routes.py` (C) and `glossary.py` (C); B and A must request terms from C by the keys in section 4 (templates may reference keys freely; C adds them).

## 7. Test strategy (tests first for money/VAT)
- Pure: `build_entry` balances for 1/many lines, mixed rates (21/9/0), credit note swap, rounding (printed VAT used, never recomputed), 0-amount line error, every `check_bookable` failure message, unsupported vat codes, credit note sign.
- Service (SQLite fixture as in `tests/extraction/conftest.py`): happy path creates entry+invoice+document link+status geboekt in one transaction; rollback on locked period leaves document `herkend`, no invoice, sequence not advanced; duplicate number refused, allowed after storno; double booking refused; trial balance 3000/1400 match; entry `source_type/source_id`; append-only (no entry updates apart from source link at creation).
- Learned: record/update counts, suggestion ranking, inactive account ignored, extraction hook fills empty lines and does not override valid ones.
- Migration test (`tests/test_migrations.py` pattern): upgrade/downgrade 0008, constraints.
- Web: preview renders plain-Dutch text and info icons; POST books and redirects; 422 on errors with message; `/inkoop` open/all tabs, search, empty state, storno'd shows "Gestorneerd"; plain-language test passes; no placeholder on `/inkoop`.
- Run full suite once at the end (no repeated runs).

## 8. Risks and decisions
- Decision: vat_code on grondslag lines only, 1400 lines without vat_code - avoids double counting in the later BTW-aangifte; voorbelasting amount comes from printed VAT (invoice is truth, extraction `assess` already tolerates 2 cents).
- Decision: payment state is derived/future (`paid_cents`); storno state derived at read time rather than synced, so no change to ledger service.
- Decision: wrong booking = storno, document stays `geboekt` (consistent with document status model and append-only rule); a re-book flow is a possible follow-up.
- Decision: refuse reverse-charge/EU/export instead of guessing; avoids wrong BTW.
- Decision: booking date = invoice date (needed for correct BTW period); no silent date shifts.
- Risk: learned-default hook touches extraction service (owned by A only); keep it small and covered by existing extraction tests.
- Risk: `routes.py` merge conflicts - single owner (C).
