# Part B report: data model, migration, services

Branch: worktree-agent-a1094c9b6ce8955aa (worktree <repo>/.claude/worktrees/agent-a1094c9b6ce8955aa).
Tests: `tests/bank` 163 passed; full suite 1593 passed after bumping the head assertion in `tests/test_migrations.py`.

## Built
- `app/models/bank.py` (`BankAccount`, `BankImportBatch`, `BankTransaction`), exported in `app/models/__init__.py`
- `migrations/versions/0009_bank_import.py` (tables, UNIQUE(bank_account_id, dedupe_key, occurrence), indexes, append-only triggers `bank_transaction_no_update` / `bank_transaction_no_delete`; UPDATE allowed only for `status` and `journal_entry_id`)
- `app/domain/bank/accounts.py`, `service.py`, `__init__.py` (re-exports everything below plus A's types)
- `app/config.py`: `bank_dir` (resolved, created by `ensure_data_dirs`)
- Tests: `tests/bank/conftest.py`, `test_accounts.py`, `test_service.py`, `test_migration.py`

## Final signatures for C (import from `app.domain.bank`)
Accounts:
- `suggest_account(session) -> Account | None`; `suggest_name(bank: str|None) -> str` ("Zakelijke rekening ING"); `selectable_accounts(session) -> list[Account]`; `BANK_NAMES` dict
- `create_bank_account(session, name, iban, account_id, bank=None) -> BankAccount`
- `update_bank_account(session, bank_account_id, *, name, bank, iban=None, account_id=None) -> BankAccount` (iban/account_id None or unchanged = unchanged; changed after an `afgerond` import raises BankImportError code ACCOUNT_IN_USE)
- `deactivate(session, bank_account_id)`, `list_bank_accounts(session, *, active_only=False) -> list[BankAccount]` (sorted by name), `get_bank_account(session, id)`, `has_imports(session, id) -> bool` (use to disable IBAN/account fields), `ensure_bank_journal(session, account, name) -> Journal`
Service:
- `start_import(session, storage: BankFileStorage, bank_account_id, filename, content) -> ImportPreview`
- `preview_batch(session, storage, batch_id) -> ImportPreview` (for `GET /bank/importeren/{batch_id}`; re-parses stored file; `already_imported_on` set when the same file was confirmed for that rekening, also for an `afgerond` batch itself)
- `confirm_import(session, storage, batch_id, include_maybe_ids: set[int]) -> ImportResult` (ids are `PreviewRow.index`; `already_processed=True` when batch was already `afgerond`, then the "Deze import is al verwerkt." notice applies; concurrent unique-key hit raises BankImportError ALREADY_IMPORTED with that same message)
- `classify(session, bank_account_id, parsed, *, batch_id=0, original_filename="", sha256="", already_imported_on=None, warnings=()) -> ImportPreview`
- `get_batch(session, batch_id) -> BankImportBatch`; `batch_file_path(storage, batch) -> Path` (for the download route; use `batch.original_filename`, ext in `batch.ext`)
- `list_transactions(session, q=None, bank_account_id=None, batch_id=None, page=1, per_page=50) -> Page` of `TransactionRow(id, booking_date, value_date, counterparty_name, counterparty_iban, description, amount_cents, balance_after_cents, bank_account_id, bank_account_name, import_batch_id, status)`
- `list_batches(session, page=1, per_page=50) -> Page` of `BatchRow(id, confirmed_at, bank_account_id, bank_account_name, original_filename, sha256, ext, format_label, bank_label, period_start, period_end, new_count, skipped_count, maybe_duplicate_count)`
- `bank_stats(session) -> BankStats(account_count [active only], transaction_count, last_imported_at)`
- `Page` is `app.domain.ledger.Page` (`items, page, per_page, total, pages`); a page beyond the last is clamped.
Errors (all plain Dutch `.message`): `BankImportError` (codes incl. WRONG_ACCOUNT, ALREADY_IMPORTED, ACCOUNT_IN_USE, BAD_IBAN plus extra codes NAME_REQUIRED, BAD_BANK, BAD_ACCOUNT, DUPLICATE_IBAN, INACTIVE_ACCOUNT, STORAGE_FAILED); `BankAccountNotFoundError` and `ImportBatchNotFoundError` (both `LedgerError`, NOT `BankImportError`: map to the standard 404). `DocumentStorageFailedError` from storage is mapped to `BankImportError("STORAGE_FAILED", ...)` in `start_import`.
Behaviour for C: `preview.format_label` is e.g. "MT940-bestand", `bank_label` "ING" (compose "MT940-bestand van ING" in the template). Warnings (no account IBAN, balance mismatch) are in `preview.warnings`. Balance mismatch amount uses `format_euro` ("€ 12,00").

## Deviations / additions
- Added beyond section 5: `preview_batch`, `get_batch`, `batch_file_path`, `has_imports`, `selectable_accounts`, `suggest_name`, `get_bank_account`, `BankAccountNotFoundError`, `ImportBatchNotFoundError`, row dataclasses (`TransactionRow`, `BatchRow`, `BankStats`).
- `selectable_accounts` returns active postable asset accounts with `selectable_bank` OR code 1210: the seed has `selectable_bank = False` for 1210 (hidden system account) although AC 2 suggests it by default.
- `suggest_account` and account validation require type asset, active, postable (not `selectable_bank`, same reason).
- "Mogelijk dubbel" matching additionally consumes each stored row at most once and ignores stored rows already exactly matched in the same file (avoids flagging a row because of a stored row that explains another).
- Period/counts on the batch: `period_*` cover the whole file; `new_count` includes opted-in maybe rows; `maybe_duplicate_count` = maybe rows not opted in.
- `confirm_import` refuses (ALREADY_IMPORTED, "Dit bestand heb je al geïmporteerd op <dd-mm-yyyy>. Er is niets nieuws.") when another batch with the same sha256 is `afgerond` for the rekening; it also re-checks the account IBAN and active state.
- Inserts run in a SAVEPOINT (`begin_nested`), so a failure leaves no partial rows and the batch `voorbeeld`; the caller still owns commit/rollback.
- `tests/test_migrations.py`: bumped the hard-coded head to `0009_bank_import` (trivial, unavoidable).

## Notes for the integrator
- `tests/conftest.py::test_settings` does not set `bank_dir`; web tests (C) should add `bank_dir=tmp_path / "data" / "bank"` there, otherwise `ensure_data_dirs` creates the real `data/bank`. I did not touch that file.
- The shared venv lacked `defusedxml` (Part A's dependency); I ran `uv pip install defusedxml` into `<repo>/.venv`. `pyproject.toml`/`uv.lock` already list it from Part A.
- The `batch` row for a file whose preview is abandoned stays `voorbeeld` (harmless); re-uploading creates a new batch.

STATUS: DONE
