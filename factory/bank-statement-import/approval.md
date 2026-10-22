VERDICT: APPROVE

## Reasoning
The round-1 blocking findings are resolved in round 2. The CAMT reversal sign bug (code review, high) is fixed: the sign now comes only from `CdtDbtInd`, with fixture correction and tests for credit and debit reversals. The "Saldo na mutatie" glossary gap (UX review, medium) is fixed: the column is now "Saldo erna" with an info icon, and the term `saldo_na_mutatie` is in the glossary. The account-form name hint no longer promises an automatic name when editing. The round-2 combined review returns PASS, and the security review of round 1 was PASS.

Process: spec approved, parts A, B and C built in parallel worktrees with disjoint files, integrated in order, one fix round after round 1, and the review cap of two rounds was respected. Test result from state.md: `1665 passed, 1 deselected`. I did not rerun the suite. I checked the implementation at spot level: the migration has the UNIQUE(bank_account_id, dedupe_key, occurrence) constraint and the append-only triggers, the IBAN and account uniqueness constraints exist, and the bank templates, glossary keys and `bank_transaction` model are in place. The account validation in `_check_account` is consistent with AC 4.

The spec is met with the deviations listed below. None of them breaks an acceptance criterion or the plain-language rule.

## Acceptance criteria check
Bankrekeningen
1. met: name, normalised IBAN with mod-97 check and uniqueness, `account_id`, `journal_id`, optional `bank`, `is_active` (`bank_account` model and migration).
2. met (with deviation): defaults 1210 then 1220 (`suggest_account`, `suggest_name`). The choice list is asset accounts with `selectable_bank` plus 1210 (service) and plus 1210/1220 (web). See Outstanding issues.
3. met: `ensure_bank_journal` reuses an active bank journal with the same account, otherwise creates BANK/BANK2/...
4. met: `_check_account` raises ACCOUNT_IN_USE with the specified text.
5. met: rename and deactivate, no delete, `has_imports` locks IBAN/account after an afgerond import.
6. met: BAD_IBAN message as specified (checked in the route/service reports; covered by tests in `tests/bank`).

Import flow
7. met: `/bank` replaces the placeholder with stat cards, per-rekening cards, tabs, and the empty state with "Bankrekening toevoegen".
8. met: `POST /bank/importeren` creates a `voorbeeld` batch and stores the file with no transactions. `POST .../bevestigen` sets `afgerond`. Confirm is idempotent.
9. met: format detection by content (CAMT, MT940, CSV), and the preview names the format and bank.
10. met: four CSV layouts in a registry (`csv_banks.py`), with the Dutch unknown-header message.
11. met: IBAN mismatch refused with the specified message. Missing IBAN gives the preview warning.
12. met: `ParsedTransaction` with integer cents, `Decimal`-based parsing, and more than two decimals rejected.
13. met: balance mismatch is a warning via `balance_difference_cents`.
14. met: a file with any bad entry is refused whole. Empty file gives the specified message.
15. met: 10 MB limit, binary and PDF rejected, encoding fallback order, `defusedxml`.
16. met: `BankFileStorage` subclasses `DocumentStorage` with `data/bank/`, content-addressed, read-only, xml/sta/csv/txt. Download route at `/bank/importeren/{id}/bestand`.

Duplicate detection
17. met: 17a (same sha256 refusal with the specified message), 17b (dedupe_key plus occurrence), 17c (fuzzy "mogelijk dubbel", default skipped, opt-in checkbox).
18. met: three groups. The server recomputes classification and ignores opt-ins for exact duplicates (`confirm_import`).
19. met as specified: cross-format overlap goes to "mogelijk dubbel". Exact cross-format equality is not guaranteed, which the spec documents as a risk.
20. met: unique constraint, IntegrityError mapped to "Deze import is al verwerkt.", idempotent confirm for afgerond batches.
21. met: result screen with the three counts and a link to the transactions.

Transactions list and history
22. met: table with datum, tegenpartij, omschrijving, bij/af colouring, bankrekening, "Saldo erna" with explainer. Filters, search, pagination, htmx partial, read-only.
23. met: "Importgeschiedenis" tab lists afgerond batches with date, rekening, file name, format/bank, period, counts, links.

Plain language (CLAUDE.md)
- met: all listed terms have glossary entries with the exact keys (`bankrekening`, `bankafschrift`, `camt053`, `mt940`, `csv_export`, `bijschrijving_afschrijving`, `dubbele_transactie`, `transactie`), plus `saldo_na_mutatie`. Existing keys `bank`, `iban`, `grootrekening`, `bankdagboek`, `bewaarplicht` are reused. Info icons are on the screens. The bank pages are in `tests/test_plain_language.py`.
- met: Dutch, plain-language errors throughout. Defaults are suggested.
- met: the Dutch UI labels follow the conventions in CLAUDE.md.

Technical approach
- met: Alembic `0009_bank_import`, models in `app/models/bank.py`, `bank_dir` in config, domain code in `app/domain/bank/`, no logic in route handlers (routes call the service). The web layer reads a few models directly in small helpers. This is a minor convention deviation, noted below.

## Outstanding issues
- Non-blocking, from the round-2 review: the "Mogelijk dubbel" rows do not show the already-stored transaction next to them (UX nice-to-have). The upload-size limit is checked after multipart spooling (security nice-to-have). Neither is an acceptance criterion; both can be follow-ups.
- Deviation from AC 2: the choice list also includes 1210 (which is `selectable_bank = false` in the seed) and, in the web route, 1220 regardless of the flag. The validator `_check_account` accepts any active postable asset account, so the list is a UI narrowing only. The B and C reports use slightly different sets (B: 1210 only; C: 1210 and 1220). This is harmless but should be unified in a follow-up.
- Deviation: the helpers in `bank_routes.py` query models directly, against the "no logic in route handlers" convention. These are read helpers, not business rules, so I did not treat this as blocking.
- Testing risk: fixtures are synthetic, built from the banks' published layouts. The spec already recommends a smoke test with a real export from each bank. This is a known risk, not a blocker.
- Visual check: no reviewer verified the screens in a real browser (the ux-ui reviewer notes this). Acceptance is based on code and template review plus the tests.
- The untracked `factory/bank-statement-import/reviews/round-2/` directory and this approval file are not committed. Commit them with the feature if they should be kept.

## What the human should look at (if HUMAN_REVIEW)
Not required for approval. Optional but recommended before merging to main:
1. Open `/bank` in a browser at desktop and phone width. Check the stat cards, the empty state, the account form defaults (1210 / BANK) and the preview page with the "Mogelijk dubbel" section.
2. Import one real bank export (CAMT or CSV from your own bank) and confirm the counts and the balance warning look right.

STATUS: DONE
