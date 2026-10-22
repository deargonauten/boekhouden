Status: APPROVED

# Spec: bank-statement-import (bankafschriften importeren)

## 1. Goal and context
The owner can register his bankrekeningen (each linked to a grootboek account and a bank dagboek), upload a bank statement file (CAMT.053 XML, MT940, or the CSV export of ING, Rabobank, ABN AMRO or bunq), review in plain Dutch what will be imported, and confirm. The system stores every transaction as a raw, immutable `bank_transaction` (integer cents, append-only), keeps the original file content-addressed, and detects duplicates so re-importing overlapping statements never creates double transactions.

This feature stores bank data only. Nothing is booked in the ledger and nothing is matched to invoices (later: "Bank reconciliation"). The data model carries the fields that feature needs (`status`, `journal_entry_id`).

Builds on: core ledger (`Account`, `Journal` type `bank` with `account_id`; seeded `1210 Bank`, `1220 Spaarrekening`, journal `BANK`), documents storage pattern (`DocumentStorage`, content-addressed, never deleted), relations (`Contact.iban`, only read for a hint), glossary, navigation (`/bank` currently a placeholder: nav item "Bank", term `bank`), `app/domain/money.py`, Alembic head `0008_purchase_booking`.

## 2. Non-goals
- Matching transactions to invoices, booking transactions to the ledger, payment marking, matching rules (separate backlog items). Transactions get `status='nieuw'` and stay that way.
- Live bank connections (PSD2/open banking), automatic downloads.
- Foreign-currency accounts: only `EUR`. A file in another currency is refused with a plain message.
- Editing or deleting imported transactions or removing an import (append-only; a wrong import is simply a later feature's concern: "negeren"/"ongedaan maken" is out of scope).
- Opening balance / balance reconciliation against the grootboek (Openingsbalans item). Statement balances are stored and checked for internal consistency only.
- Other banks / other CSV layouts than the four listed (the parser registry is extensible; unknown layout gives a plain error).
- Credit-card statements, savings interest booking, PDF statements.

## 3. User stories
- As owner I add my business bankrekening once (name, IBAN, which grootboek account it is) and get sensible defaults (account 1210, dagboek BANK).
- As owner I drop the file I downloaded from my bank, the program recognises the format and bank, shows "Gevonden: 42 transacties, 40 nieuw, 2 al eerder geïmporteerd" and I confirm.
- As owner I can import the same or an overlapping statement again without getting doubles.
- As owner I see all imported transactions per bankrekening with date, naam, omschrijving, bij/af and search, and the import history with the original file.
- As owner I get a clear Dutch message when a file cannot be read, belongs to a different IBAN, or is not a bank file.

## 4. Acceptance criteria

### Bankrekeningen
1. A `bankrekening` has: name (e.g. "Zakelijke rekening ING"), IBAN (validated: country + length + mod-97, stored normalised uppercase without spaces, unique), `account_id` (grootboek account, type `asset`, postable, active), `journal_id` (bank dagboek), optional `bank` (`ing|rabobank|abn_amro|bunq|overig`, used as a CSV format hint), `is_active`.
2. Suggested defaults on the add form: grootboekrekening = first active asset account among `1210`, then `1220`, not already linked to another bankrekening; name prefilled from the chosen bank. Account choice list is limited to asset accounts with `selectable_bank = true` (existing flag).
3. Dagboek: on creation the existing active bank journal whose `account_id` equals the chosen account is reused; if none exists a new journal of type `bank` is created (code `BANK`, else `BANK2`, `BANK3`..., name = bankrekening name). The user never has to pick a dagboek.
4. A grootboek account can be linked to at most one bankrekening (error: "Deze grootboekrekening hoort al bij <naam>. Kies een andere rekening of gebruik die bankrekening.").
5. Bankrekeningen can be renamed and deactivated, never deleted; a bankrekening with imports cannot change IBAN or account (fields disabled with explanation). Inactive rekeningen accept no new imports.
6. Invalid IBAN gives: "Dit IBAN-nummer klopt niet. Controleer of je alle tekens hebt overgenomen (bijvoorbeeld NL91 ABNA 0417 1643 00)."

### Import flow
7. `GET /bank` (replaces placeholder) shows: stat cards (Aantal bankrekeningen, Transacties, Laatst geïmporteerd), a card per bankrekening with button "Afschrift importeren", and tabs "Transacties" and "Importgeschiedenis". Empty state (no bankrekening): plain Dutch text and button "Bankrekening toevoegen".
8. Upload (`POST /bank/importeren`, multipart: file + bankrekening) is a two-step flow: step 1 parses and stores the original file and an `import_batch` with `status='voorbeeld'` and shows a preview; step 2 `POST /bank/importeren/{batch_id}/bevestigen` inserts the transactions and sets the batch `status='afgerond'`. Step 1 inserts no transactions. An abandoned preview batch is harmless (file kept, no transactions); it is listed nowhere except via its preview URL, expires from the history list by simply not being `afgerond`.
9. Format detection is automatic and by content, never by file extension alone: CAMT.053 (XML with a `BkToCstmrStmt` element, namespaces `camt.053.001.0x`), MT940 (SWIFT blocks with `:20:`, `:25:`, `:60F:`, `:61:`, `:62F:`), CSV (delimiter and encoding sniffed; header row matched against the bank layouts below). The preview names what was found: "CAMT.053-bestand van ING" / "CSV-export van Rabobank".
10. CSV layouts supported (one parser each, header-driven, case-insensitive, Dutch and English headers where the bank exports both):
    - ING: `Datum;Naam / Omschrijving;Rekening;Tegenrekening;Code;Af Bij;Bedrag (EUR);Mutatiesoort;Mededelingen` (and the newer variant with `Saldo na mutatie`, `Tag`), date `YYYYMMDD`, decimal comma, sign via `Af`/`Bij`.
    - Rabobank: `IBAN/BBAN;Munt;BIC;Volgnr;Datum;Rentedatum;Bedrag;Saldo na trn;Tegenrekening IBAN/BBAN;Naam tegenpartij;...;Omschrijving-1..3;...`, signed amount.
    - ABN AMRO: tab-separated `.TAB` export (`Rekeningnummer, Muntsoort, Transactiedatum, Beginsaldo, Eindsaldo, Rentedatum, Transactiebedrag, Omschrijving`), counterparty parsed from the SEPA-style omschrijving (`/NAME/`, `/TRTP/`, `/IBAN/`, `/REMI/`, `/EREF/`) when present.
    - bunq: `Date,Amount,Account,Counterparty,Name,Description` (comma separated, signed amount, ISO date; `Counterparty` is the tegenrekening IBAN).
    Because layouts vary per export version, the parser registry is a list of `CsvLayout` definitions (header signature + column mapping + date format + sign rule) so a variant is data, not new code. Unrecognised header: "Dit CSV-bestand herkennen we niet. Download het afschrift als CAMT.053 (XML) of MT940 als je bank dat aanbiedt, of kies het exportformaat van ING, Rabobank, ABN AMRO of bunq."
11. IBAN check: if the file carries the account IBAN (CAMT `Acct/Id/IBAN`, MT940 `:25:`, CSV account column) and it differs from the chosen bankrekening, import is refused: "Dit afschrift hoort bij <IBAN>, maar je koos <naam> (<IBAN>). Kies de juiste bankrekening." Files without an account IBAN (some CSVs) are accepted with a preview warning "In dit bestand staat geen rekeningnummer; controleer of dit de juiste bankrekening is."
12. Each parsed transaction becomes a `ParsedTransaction`: `booking_date` (required), `value_date` (optional), `amount_cents` (signed int: positive = bij, negative = af, never zero), `currency='EUR'`, `counterparty_name`, `counterparty_iban` (normalised, optional), `description` (all remittance text joined with single spaces, whitespace collapsed), `end_to_end_id`, `bank_reference` (CAMT `AcctSvcrRef`/`NtryRef`, MT940 `:61:` bank reference, CSV `Volgnr`), `balance_after_cents` (when given), `raw` (the source fragment as text for audit). Amounts are parsed from strings to integer cents without floats (`Decimal`/string split), both `1.234,56` and `1234.56` styles per the format; more than 2 decimals is an error.
13. Internal consistency checks, reported as warnings (not blocking) in the preview: CAMT/MT940 `opening balance + sum(transactions) != closing balance` ("De saldi in het bestand kloppen niet met de transacties: verschil €x. Controleer of het bestand compleet is."); when both statement-end balance and per-line balance exist, the same check per line is not required.
14. Unparseable lines/entries do not abort silently: a file with at least one unparseable transaction is refused as a whole with the first problem named (line/entry number + reason in plain Dutch). Partial imports do not exist. Empty file (zero transactions) gives "Er staan geen transacties in dit bestand."
15. File limits: max 10 MB; non-text/binary files, wrong types and unreadable encodings give plain errors (UTF-8, UTF-8 BOM, Windows-1252/ISO-8859-1 tried in that order for CSV/MT940; CAMT uses its XML declaration). XML parsing must be safe against entity expansion/external entities (use `defusedxml` or stdlib with entities disabled; add `defusedxml` to `pyproject.toml`).
16. Original file storage: bytes stored content-addressed via the existing `DocumentStorage` pattern in a separate root `data/bank/` (`settings.bank_dir`, created by `ensure_data_dirs`), layout `<sha256[0:2]>/<sha256>.<ext>` with ext in `xml|sta|csv|txt`, read-only, never deleted or overwritten. The batch row keeps `original_filename` (sanitised), `sha256`, `ext`, `size`, `detected_format`, `detected_bank`, `imported_at`. A link "Origineel bestand downloaden" on the batch serves it (`GET /bank/importeren/{batch_id}/bestand`).

### Duplicate detection
17. Three levels, evaluated at preview time and re-evaluated inside the confirm transaction:
    a. Same file again (same `sha256` already `afgerond` for this bankrekening): preview says "Dit bestand heb je al geïmporteerd op <datum>. Er is niets nieuws." and confirm is disabled. A same-bytes file for a different bankrekening is allowed (IBAN check will normally block it first).
    b. Transaction level, deterministic key `dedupe_key` = sha256 of `bankrekening_id | booking_date | amount_cents | normalised counterparty_iban | end_to_end_id-or-bank_reference-or-"" | normalised description`, plus `occurrence` = n-th occurrence of identical keys within one file (so two truly identical payments in the same file, e.g. two coffee payments, are both kept). A transaction counts as already imported when a stored row exists with the same `dedupe_key` and `occurrence`. Normalisation: trimmed, casefolded, whitespace collapsed, IBAN without spaces.
    c. Fuzzy "mogelijk dubbel": no exact key match but a stored row in the same bankrekening has same `booking_date` and `amount_cents` and the same counterparty IBAN (or both empty) while the description differs (banks change description text between CSV and CAMT exports). Shown as "Mogelijk dubbel" in the preview, default NOT imported, with a checkbox per row "Toch importeren" that the user may tick.
18. Preview lists three groups with counts: Nieuw (imported on confirm), Al eerder geïmporteerd (skipped, not shown by default, expandable), Mogelijk dubbel (default skipped, user can opt in). The confirm form posts the ids of opted-in rows; the server recomputes classification and ignores a posted opt-in for rows that are exact duplicates.
19. Overlapping statements (same period imported from two different files or formats, e.g. CAMT then CSV) must not create doubles for transactions that agree on date, amount and counterparty IBAN: covered by 17c (flagged, default skipped) because description text differs between formats. Exact cross-format equality is not guaranteed and is documented in the risks.
20. DB-level safety: `UNIQUE(bankrekening_id, dedupe_key, occurrence)` on `bank_transaction`; a concurrent double-confirm hits the constraint and is mapped to "Deze import is al verwerkt." (confirm is idempotent: confirming an `afgerond` batch redirects to its result with that notice and inserts nothing).
21. Result screen after confirm: "42 transacties geïmporteerd, 2 overgeslagen (al eerder geïmporteerd), 1 mogelijk dubbel overgeslagen", link to the transactions of that import.

### Transactions list
22. Tab "Transacties": table (datum, tegenpartij, omschrijving, bij/af in green/red, bankrekening, saldo na mutatie when known), filter by bankrekening and import, search on naam/omschrijving/IBAN/bedrag, pagination, htmx partial like `/inkoop`. Sorted by `booking_date` desc, then `id` desc. Read-only: no edit/delete actions. Mobile layout works at phone width (card/table components as elsewhere).
23. Tab "Importgeschiedenis": per batch (afgerond only): datum, bankrekening, bestandsnaam, formaat/bank, periode (first-last booking date), counts (nieuw/overgeslagen), link to the original file and to its transactions.

### Plain-language (CLAUDE.md global requirement)
Terms introduced or used on the new screens, each with a glossary entry in `app/domain/glossary.py` (with `detect` patterns where generic) and an info icon on screen:
- `bankrekening` ("Bankrekening" / plain: "Je rekening bij de bank"; explains it is linked to one grootboekrekening so later bookings know where the money goes),
- `bankafschrift` ("Bankafschrift" / plain: "Overzicht van bij- en afschrijvingen"; explains downloading it from internet banking),
- `camt053` ("CAMT.053" / plain: "Bankbestand (XML)"; the standard XML statement most banks offer),
- `mt940` ("MT940" / plain: "Bankbestand (oud formaat)"),
- `csv_export` ("CSV" / plain: "Bankbestand voor Excel"),
- `bijschrijving_afschrijving` ("Bij / Af" / plain: "Geld erbij / geld eraf"),
- `dubbele_transactie` ("Dubbele transactie" / plain: "Staat er al"; explains the checks and why "mogelijk dubbel" needs a look),
- `transactie` ("Transactie" / plain: "Een bij- of afschrijving"),
- `bankdagboek` exists: its explainer is reused for the dagboek the program picks automatically,
- existing reused: `bank`, `iban`, `grootboekrekening`/`grootrekening` (use the existing key actually in the glossary), `bewaarplicht` if present (explains why the original file is kept).
Suggested defaults: grootboekrekening and dagboek (AC 2, 3), bank for CSV layout (from rekening or auto-detected), all new rows ticked except "mogelijk dubbel". Plain-Dutch errors are listed in AC 4, 6, 10, 11, 13, 14, 15, 17, 20. `tests/test_plain_language.py` must keep passing.

## 5. Technical approach

### Data model (Alembic `0009_bank_import.py`, models in `app/models/bank.py`, exported from `app/models/__init__.py`)
- `bank_account`: `id`, `name` str NOT NULL, `iban` str NOT NULL UNIQUE (normalised), `bank` str NULL CHECK in (`ing`,`rabobank`,`abn_amro`,`bunq`,`overig`), `account_id` FK account NOT NULL UNIQUE, `journal_id` FK journal NOT NULL, `is_active` bool default 1, `created_at`.
- `bank_import_batch`: `id`, `bank_account_id` FK NOT NULL, `status` CHECK in (`voorbeeld`,`afgerond`), `original_filename`, `sha256`, `ext`, `size` int, `detected_format` CHECK in (`camt053`,`mt940`,`csv`), `detected_bank` str NULL, `period_start`/`period_end` date NULL, `new_count`, `skipped_count`, `maybe_duplicate_count` int default 0, `created_at`, `confirmed_at` NULL. Index on (`bank_account_id`, `sha256`).
- `bank_transaction`: `id`, `bank_account_id` FK NOT NULL, `import_batch_id` FK NOT NULL, `booking_date` date NOT NULL, `value_date` date NULL, `amount_cents` int NOT NULL CHECK `<> 0`, `currency` str default `EUR` CHECK = `EUR`, `counterparty_name` NULL, `counterparty_iban` NULL, `description` str NOT NULL default '', `end_to_end_id` NULL, `bank_reference` NULL, `balance_after_cents` int NULL, `dedupe_key` str NOT NULL, `occurrence` int NOT NULL default 1, `raw` text NOT NULL, `status` CHECK in (`nieuw`,`geboekt`,`genegeerd`) default `nieuw`, `journal_entry_id` FK journal_entry NULL, `created_at`. `UNIQUE(bank_account_id, dedupe_key, occurrence)`. Indexes: (`bank_account_id`, `booking_date`), (`bank_account_id`, `booking_date`, `amount_cents`). Append-only: the import code only inserts; `status`/`journal_entry_id` are reserved for the reconciliation feature (the only future writers). SQLite triggers forbidding UPDATE of every other column and all DELETEs are added in the migration and tested.
- Preview persistence: the parsed transactions of a `voorbeeld` batch are NOT stored in tables; confirm re-reads the original file from `data/bank/` by `sha256` and re-parses (single source of truth, no stale preview data). Deterministic parsers make this safe.
- Money: integer cents everywhere. Never floats.

### Domain (`app/domain/bank/`; no logic in routes)
- `types.py`: frozen dataclasses `ParsedTransaction`, `ParsedStatement` (`account_iban`, `currency`, `opening_cents`, `closing_cents`, `transactions`, `format`, `bank`), `ImportPreview` (counts + three row lists), `BankImportError(DomainError subclass)` with Dutch `message` and a `code` (`UNKNOWN_FORMAT`, `PARSE_ERROR`, `WRONG_ACCOUNT`, `ALREADY_IMPORTED`, `EMPTY`, `FILE_TOO_BIG`, `BAD_IBAN`, `ACCOUNT_IN_USE`). Plain messages only in routes.
- `iban.py`: `normalize_iban`, `is_valid_iban` (mod-97).
- `amounts.py`: `parse_amount(text, style) -> int` (string to cents, no floats).
- `parsers/`: `base.py` (`StatementParser` protocol: `detect(content: bytes) -> bool`, `parse(content: bytes, hint_bank) -> ParsedStatement`), `camt053.py` (supports camt.053.001.02/.08; `Ntry` with `NtryDtls/TxDtls` splitting: one transaction per `TxDtls` when an entry has several, otherwise per `Ntry`; `CdtDbtInd` for sign; `RvslInd` reversal flips sign), `mt940.py` (`:61:` + `:86:` incl. structured `?20..?29`/`/NAME/`-style subfields, YYMMDD dates, `C/D/RC/RD` marks, comma decimals), `csv_banks.py` (`CsvLayout` registry + sniffing for ING, Rabobank, ABN AMRO, bunq), `__init__.py` with `parse_statement(content, hint_bank=None) -> ParsedStatement` that tries parsers in order CAMT, MT940, CSV.
- `dedupe.py`: `normalize_text`, `compute_keys(rekening_id, parsed) -> list[(dedupe_key, occurrence)]`, `classify(session, rekening_id, parsed) -> ImportPreview` (nieuw / bestaand / mogelijk_dubbel per AC 17).
- `storage.py`: `BankFileStorage` (same atomic, read-only, content-addressed, never-delete behaviour as `DocumentStorage`; may subclass/compose it with a different root and allowed ext set; must not modify `app/domain/documents/`).
- `accounts.py`: `suggest_account(session)`, `create_bank_account(session, name, iban, account_id, bank)`, `update_bank_account`, `deactivate`, `list_bank_accounts`, `ensure_bank_journal(session, account, name) -> Journal` (AC 3).
- `service.py`: `start_import(session, storage, bank_account_id, filename, content) -> ImportPreview` (validates size/type, parses, IBAN check, hashing, stores file, creates `voorbeeld` batch, classifies; returns preview incl. warnings), `confirm_import(session, storage, batch_id, include_maybe_ids: set[int]) -> ImportResult` (re-reads file, re-parses, re-classifies, inserts `nieuw` + opted-in `mogelijk_dubbel`, sets counts/period/status; idempotent), `list_transactions(session, q, bank_account_id, batch_id, page)`, `list_batches(session, page)`, `bank_stats(session)`. All functions flush, never commit; the caller owns the transaction (same convention as documents service).

### Web
- `app/web/bank_routes.py`: `GET /bank`, `GET /bank/transacties` (htmx partial), `GET/POST /bank/rekeningen/nieuw`, `GET/POST /bank/rekeningen/{id}/bewerken`, `POST /bank/importeren`, `GET /bank/importeren/{batch_id}` (preview), `POST /bank/importeren/{batch_id}/bevestigen`, `GET /bank/importeren/{batch_id}/bestand`. Thin handlers; `BankImportError`/`LedgerError` render `message` via `error_box` with status 422, values kept; never codes or tracebacks. Unknown ids give the standard 404.
- `app/web/routes.py`: include `bank_router` before the placeholder loop and add `"bank"` to `LEDGER_KEYS`.
- Templates under `app/web/templates/bank/` (`index.html`, `_transactions.html`, `_batches.html`, `account_form.html`, `preview.html`, `result.html`); CSS `app/web/static/css/bank.css`.
- Config: `bank_dir: Path = Path("data/bank")` in `app/config.py`, resolved and created like `documents_dir`.

### Error handling
Every domain failure is a `BankImportError` with a Dutch message that says what is wrong and what to do. Parse errors name the entry/line. `IntegrityError` on the unique key is mapped to AC 20. Files written before a rollback stay on disk (content-addressed, reused on re-upload, never deleted).

## 6. Work breakdown (3 parts, disjoint files)

**Part A - parsers and pure domain (critical path, no DB, no web)**
Owns: `app/domain/bank/types.py`, `iban.py`, `amounts.py`, `parsers/**`, `dedupe.py` (pure functions `normalize_text`, `compute_keys`; the DB-backed `classify` lives in B's `service.py` and calls these), `storage.py`, `pyproject.toml` (`defusedxml` only), `uv.lock`, `tests/bank/parsers/**` (fixtures: small synthetic but realistic sample files for CAMT.053 (.02 and .08), MT940 (ING, Rabobank flavour), and the four CSV layouts incl. edge cases: windows-1252, BOM, multi-line `:86:`, split `TxDtls`, reversal, two identical lines in one file, bad amount, wrong IBAN), `tests/bank/test_iban_amounts.py`, `tests/bank/test_dedupe_keys.py`, `tests/bank/test_storage.py`).
Delivers the signatures in section 5: `parse_statement`, `ParsedTransaction/ParsedStatement`, `compute_keys`, `BankFileStorage`, `normalize_iban/is_valid_iban`, `BankImportError`.

**Part B - data model, migration, services**
Owns: `app/models/bank.py`, `app/models/__init__.py`, `migrations/versions/0009_bank_import.py`, `app/domain/bank/__init__.py`, `accounts.py`, `service.py` (including `classify` and `ImportPreview` assembly), `app/config.py` (`bank_dir`), `tests/bank/conftest.py`, `tests/bank/test_accounts.py`, `tests/bank/test_service.py`, `tests/bank/test_migration.py`.
Depends on A's types and parsers (A publishes `types.py` + `parse_statement` signature first; B may stub with the dataclasses until A merges). Integration order: A, then B.

**Part C - web, glossary, wiring**
Owns: `app/web/bank_routes.py`, `app/web/routes.py`, `app/web/templates/bank/**`, `app/web/static/css/bank.css`, `app/domain/glossary.py` (all new terms in section 4 with the exact keys), `app/web/navigation.py` (only if label/term changes), `tests/test_bank_web.py`, glossary/plain-language test additions.
Depends on B's service functions (`start_import`, `confirm_import`, `list_transactions`, `list_batches`, `bank_stats`, account functions). C works against the signatures in section 5 and the dataclasses `ImportPreview` (`format_label`, `bank_label`, `warnings`, `new_rows`, `existing_rows`, `maybe_rows`, `already_imported_on`, `period_start/end`), `ImportResult` (`new_count`, `skipped_count`, `maybe_skipped_count`, `batch_id`). Those two dataclasses are defined in `types.py` by A at the start so all parts share them.
Integration point: `routes.py` (C only) and `glossary.py` (C only); A and B reference terms by key and ask C to add them.

## 7. Test strategy (tests first for anything touching money)
- Amounts: every format style to integer cents, rounding never needed, >2 decimals rejected, sign handling (ING Af/Bij, CAMT CdtDbtInd, MT940 C/D/RC/RD).
- Parsers: golden files per format and bank asserting the exact list of `ParsedTransaction`s; sum of amounts equals closing minus opening balance; detection by content (wrong extension still works, HTML/PDF rejected); encoding variants; malformed entries produce the Dutch error naming the entry; XML entity-expansion payload rejected.
- Dedupe: key stability across whitespace/case/IBAN-format differences; two identical lines in one file get occurrence 1 and 2; re-import of the same file yields 0 new; overlapping file yields only the new rows; same bytes different format (CAMT vs CSV of the same transactions) gives "mogelijk dubbel" not new; opted-in maybe row is imported; forged opt-in for an exact duplicate ignored; concurrent confirm hits the unique constraint and inserts nothing twice.
- Service (SQLite fixture): `start_import` stores file content-addressed (path exists, read-only, same bytes), creates `voorbeeld` batch, no transactions; `confirm_import` atomic (failure leaves no partial rows and batch stays `voorbeeld`), idempotent; wrong IBAN refused; inactive rekening refused; period and counts correct.
- Accounts: IBAN validation, default account suggestion, journal reuse vs creation (`BANK`, `BANK2`), one rekening per grootboekrekening, IBAN/account locked after imports.
- Migration: upgrade/downgrade `0009`, constraints, UNIQUE key, append-only triggers (UPDATE of amount and DELETE rejected, status update allowed).
- Web: `/bank` empty state and populated; add rekening with defaults; upload CAMT/MT940/CSV happy path to preview to confirm to result; 422 with plain message for wrong file, wrong IBAN, empty file; same file again shows "al geïmporteerd" and disabled confirm; transactions search and pagination; original file download returns identical bytes; info icons for every new term; no placeholder on `/bank`; plain-language test passes.
- Run the full suite once at the end.

## 8. Risks and decisions
- Decision (technical): store raw transactions in their own tables and keep preview state out of the DB (re-parse the stored original on confirm). Rationale: single source of truth, no stale/duplicated parsed data, parsers are deterministic.
- Decision: the original file lives under `data/bank/`, not in the document inbox. Rationale: the documents table has invoice-specific statuses and extraction semantics; same content-addressed, never-delete guarantees are reused via a separate storage root without touching `app/domain/documents/`.
- Decision: a bankrekening auto-creates/reuses its bank dagboek. Rationale: the ledger requires `Journal.account_id` for type `bank`, and the user must not need to understand dagboeken; the later booking feature needs the journal.
- Decision: duplicate detection is deterministic key + occurrence index (exact), plus a fuzzy "mogelijk dubbel" that is skipped by default but overridable. Rationale: silently dropping legitimate repeated payments is worse than asking; silently importing duplicates corrupts the books. Unavoidable trade-off: identical same-day same-amount payments across overlapping files in different formats are flagged for a human glance.
- Decision: partial files are refused as a whole (no partial import) so the owner never has an unknown gap in his bank data.
- Decision: no negation/removal of an import in this feature; append-only is enforced by triggers. Rationale: bewaarplicht; a "negeren" status is reserved for reconciliation.
- Decision: `defusedxml` as the only new dependency for safe XML parsing; CAMT, MT940 and CSV otherwise use stdlib (own MT940 parser, no `mt-940` dependency) to keep the package list small and behaviour testable.
- Risk: CSV layouts differ between export versions and years. Mitigation: header-signature registry (`CsvLayout`) so variants are data; unknown header gives an actionable message pointing to CAMT/MT940. Sample files are synthetic from the banks' published layouts, so a real-export smoke test by the owner is recommended after merge.
- Risk: ABN AMRO `.TAB` omschrijving parsing is heuristic; the raw text is always kept in `description` and `raw`.
- Risk: `routes.py`, `glossary.py` and `app/models/__init__.py` merge conflicts: single owner each (C, C, B).
