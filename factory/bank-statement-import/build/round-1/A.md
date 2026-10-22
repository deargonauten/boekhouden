# Part A report: parsers and pure domain

Branch: worktree-agent-aa26819b0c250b62f. Tests: `tests/bank` 111 passed; full suite 1541 passed.

## Built
- `app/domain/bank/types.py`, `iban.py`, `amounts.py`, `dedupe.py`, `storage.py`
- `app/domain/bank/parsers/{__init__,base,camt053,mt940,csv_banks}.py`
- `pyproject.toml` + `uv.lock`: `defusedxml>=0.7.1`
- Tests: `tests/bank/{test_iban_amounts,test_dedupe_keys,test_storage}.py`, `tests/bank/parsers/test_parsers.py`, fixtures in `tests/bank/parsers/fixtures/`
- Empty `app/domain/bank/__init__.py` (B owns/fills it), empty `tests/bank/__init__.py` and `tests/bank/parsers/__init__.py`.

## Signatures for B and C
- `BankImportError(code, message)` subclasses `LedgerError` (there is no `DomainError` in the repo). Code constants in types.py: UNKNOWN_FORMAT, PARSE_ERROR, WRONG_ACCOUNT, ALREADY_IMPORTED, EMPTY, FILE_TOO_BIG, BAD_IBAN, ACCOUNT_IN_USE. Also `MAX_FILE_BYTES`, `BANKS`, `FORMATS`.
- `ParsedTransaction(booking_date, amount_cents, value_date=None, currency="EUR", counterparty_name=None, counterparty_iban=None, description="", end_to_end_id=None, bank_reference=None, balance_after_cents=None, raw="")` (frozen)
- `ParsedStatement(account_iban, currency, opening_cents, closing_cents, transactions: tuple, format, bank)` with property `balance_difference_cents` (None if balances unknown, 0 if consistent; otherwise closing - (opening + sum)). B uses it for the AC 13 warning.
- `PreviewRow(index, transaction, dedupe_key, occurrence, matched_transaction_id=None)`. `index` is the 0-based position in the file and is the id for the "Toch importeren" opt-in.
- `ImportPreview(batch_id, bank_account_id, original_filename, sha256, format_label, bank_label, period_start, period_end, new_rows=(), existing_rows=(), maybe_rows=(), warnings=(), already_imported_on: datetime|None=None)`; properties `new_count`, `existing_count`, `maybe_count`, `total_count`, `can_confirm`. The spec only named some fields, so batch_id, bank_account_id, original_filename, sha256 and the properties are my additions.
- `ImportResult(batch_id, new_count, skipped_count, maybe_skipped_count, already_processed=False)`
- `parse_statement(content: bytes, hint_bank=None) -> ParsedStatement` (in `app.domain.bank.parsers`). It checks size (FILE_TOO_BIG), blank (EMPTY), PDF and non-text (UNKNOWN_FORMAT), and zero transactions (EMPTY, "Er staan geen transacties in dit bestand."). Also exported there:
  - `format_description(statement)` returns "CAMT.053-bestand van ING" / "CSV-export van Rabobank".
  - `FORMAT_LABELS`, `BANK_LABELS` (use for `format_label` and `bank_label`).
- `compute_keys(bank_account_id, parsed: ParsedStatement | Iterable[ParsedTransaction]) -> list[(dedupe_key, occurrence)]`, plus `dedupe_key(id, tx)` and `normalize_text`.
- `normalize_iban`, `is_valid_iban`, `find_iban` (valid IBAN inside free text), `bank_from_iban` in `iban.py`. `parse_amount(text, style)` with styles `nl|en|mt940` in `amounts.py`.
- `BankFileStorage(root)` subclasses `DocumentStorage` (same API: `write(content, ext) -> StoredFile`, `path_for`, `exists`, `open`). Extensions are limited to xml/sta/csv/txt (ValueError otherwise) and sha256 is validated. A write failure raises `DocumentStorageFailedError` with a data/bank message. `storage_ext(detected_format, filename)` picks the ext: camt053 -> xml, mt940 -> sta (txt if the filename ends in .txt), csv -> csv.
- B should map `DocumentStorageFailedError` to a user message itself.

## Behaviour notes
- The IBAN found in the file is `ParsedStatement.account_iban`. It is None when the file has no valid IBAN. ABN AMRO .TAB exports with a numeric rekeningnummer therefore give None (B shows the AC 11 warning).
- CSV with several different account IBANs, or CAMT/MT940 with several, is refused (PARSE_ERROR).
- CAMT entries with a Sts other than BOOK (e.g. PDNG) are skipped.
- RvslInd=true flips the sign. The counterparty is picked from the effective sign (positive = Dbtr, negative = Cdtr).
- "NOTPROVIDED" / "NONREF" references become None.
- `description` for ING slash-style MT940 is REMI (USTD// prefix removed), or TRTP when there is no REMI.
- MT940 free text (Rabobank) is kept whole as description, with counterparty_iban extracted and no name. Structured `?20..?33` gives name and description.

## Deviations
- `DomainError` does not exist; used `LedgerError` as the base.
- Added `PreviewRow`; `ImportPreview` rows hold `PreviewRow` objects (not bare ParsedTransactions).
- Opening/closing balance is None for CSV (not required by the spec).
- `ruff` is not configured in the repo, so I did not reformat.

## Notes for the integrator
- B can merge cleanly: A did not touch `app/models`, `config.py` or `app/domain/bank/__init__.py` (empty here). `tests/bank/__init__.py` is empty in A and may also be created by B; identical content.
- Fixtures are synthetic (see risks in the spec): a real-export smoke test by the owner is still recommended.
