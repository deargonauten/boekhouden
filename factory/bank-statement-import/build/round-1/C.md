# Part C report: web, glossary, wiring

Branch: worktree-agent-ab334b1e5d382fc3a (Part A merged underneath). Part B is NOT present: the committed branch cannot import until B is merged (bank_routes imports app.domain.bank.service/accounts and app.models.bank).

## Built
- `app/web/bank_routes.py`, wired in `app/web/routes.py` (`bank_router` + `"bank"` in LEDGER_KEYS).
- Templates `app/web/templates/bank/`: index, _transactions, _batches, account_form, preview, result, plus `upload.html` (extra: the upload page behind "Afschrift importeren"; also the error page for failed uploads).
- `app/web/static/css/bank.css`.
- Glossary: bankrekening, bankafschrift, camt053, mt940, csv_export, bijschrijving_afschrijving, dubbele_transactie, transactie (exact spec keys). Existing keys reused: bank, iban, grootrekening, bankdagboek, bewaarplicht.
- Routes: GET /bank (tabs via `?tab=geschiedenis`, filters `q`, `rekening`, `importeren`, `page`), GET /bank/transacties (htmx partial), GET/POST /bank/rekeningen/nieuw, GET/POST /bank/rekeningen/{id}/bewerken (POST `actie=deactiveren` deactivates), GET/POST /bank/importeren (GET = upload form, `?rekening=ID`), GET /bank/importeren/{id} (preview for `voorbeeld`, result for `afgerond`; `?melding=al_verwerkt` adds the notice), POST .../bevestigen (field `include_maybe` = PreviewRow.index list), GET .../bestand (attachment download).
- Tests: `tests/test_bank_web.py` (50 tests, uses an in-memory fake of B's service/accounts with the real Part A parsers/keys/storage). Updated `tests/test_web.py` (/bank no longer a placeholder), `tests/test_plain_language.py` (4 bank pages added to PAGES), `tests/domain/test_glossary.py` (key regex now `[a-z][a-z0-9_]*`).
- Results (with throwaway local stubs for B, since removed): `tests/test_bank_web.py` 50 passed; full suite 1606 passed.

## Deviations
1. Glossary key regex relaxed to allow digits (spec keys `camt053`, `mt940` violate `[a-z_]+`); also the Term comment.
2. Account choice list = active postable assets with `selectable_bank` OR code in (1210, 1220). Reason: seed marks system account 1210 as `selectable_bank=false` (default_contexts hides system codes), but spec AC2 makes 1210 the default. Spec/B should confirm.
3. Detect patterns: only bankafschrift, camt053, mt940, csv_export have real patterns; bankrekening, bijschrijving_afschrijving, dubbele_transactie, transactie use the never-matching pattern (too generic) but all are shown with info icons.
4. Extra route `GET /bank/importeren` (upload form) and template `upload.html`.
5. Word choices avoid bare glossary terms (e.g. table header "Toegevoegd", "Rekening").

## What the integrator must check against B (assumptions I coded to)
Names/attributes not fixed by spec section 5:
- `app.domain.bank.service.get_preview(session, storage, batch_id) -> ImportPreview` is REQUIRED and not in the spec (GET preview of an existing `voorbeeld` batch). It may raise BankImportError.
- `accounts.list_bank_accounts(session)` must return ALL rows (active and inactive); the routes filter. Objects need `id, name, iban, bank, account_id, is_active`.
- `accounts.suggest_account(session)` returns an object with `.id` (Account) or None.
- `accounts.create_bank_account(session, name, iban, account_id, bank)` (bank may be None); `accounts.update_bank_account(session, bank_account_id, name=, bank=, iban=, account_id=)` where `iban=None`/`account_id=None` mean "unchanged" (routes pass None when the account has finished imports); `accounts.deactivate(session, bank_account_id)`.
- `service.list_transactions(session, q=, bank_account_id=, batch_id=, page=)` and `service.list_batches(session, page=)` return a page object with `.items .page .per_page .total`. Transactions need `booking_date, counterparty_name, counterparty_iban, description, amount_cents, bank_account_id, balance_after_cents`. Batches need `id, confirmed_at, created_at, bank_account_id, original_filename, detected_format, detected_bank, period_start, period_end, new_count, skipped_count, maybe_duplicate_count`.
- `service.bank_stats(session)` needs `.account_count, .transaction_count, .last_imported_at` (datetime or None). Adjust `_stats_cards` in bank_routes if B names differ.
- Result screen reads the batch columns: `skipped_count` = exact duplicates skipped, `maybe_duplicate_count` = maybe rows NOT imported (i.e. ImportResult.maybe_skipped_count). B must store them that way.
- Routes read models directly in small helpers (`_get_bank_account`, `_get_batch`, `_has_imports`, and the Account query in `_account_choices`): need `app.models.bank.BankAccount` and `BankImportBatch` with the spec's columns.
- `request.app.state.settings.bank_dir` (B adds to config). Storage dependency `bank_routes.get_storage` returns `BankFileStorage`.
- Errors: all `LedgerError` (BankImportError, DocumentStorageFailedError) render `message` with 422 (500 for DOCUMENT_STORAGE_FAILED). `IntegrityError` on confirm becomes redirect to `?melding=al_verwerkt` ("Deze import is al verwerkt."); B should also return `ImportResult(already_processed=True)` for an `afgerond` batch.
- The routes commit after each service call; B only flushes.
- My web tests monkeypatch the service/accounts functions and the route helpers; after integration, add one real end-to-end pass (upload -> preview -> confirm) through the real B and check the bank pages in `tests/test_plain_language.py` (they run against the real service on an empty DB).

STATUS: DONE
