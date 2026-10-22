# Builder report: delete-unbooked-documents (round 1, single part)

Branch: worktree-agent-a2457baf461aa090b

## Done
- Domain: `delete_document`, `can_delete` (service.py, exported), `DocumentDeleteNotAllowedError` (`DOCUMENT_DELETE_NOT_ALLOWED`), `DocumentStorage.remove` (validated sha/ext, exact path, chmod, shard rmdir), `BankFileStorage.remove` raises. Docstrings corrected (storage, service, models/documents, bank storage).
- Web: `GET/POST /inbox/{id}/verwijderen`, `inbox/delete.html`, buttons in list rows and `_detail_body.html` (drawer + detail), geboekt hint, `?melding=verwijderd` notice, hint texts updated (list.html, _detail_body.html). bank/upload.html untouched.
- Extraction routes: `DocumentNotFoundError` handled in `/uitlezen` (404 list page with message), `/uitlezen-alles` (continues), review save.
- CLAUDE.md amended (AC 14), glossary (bewaarplicht text, new `verwijderen_document`).
- Tests: `tests/documents/test_delete.py`, `tests/test_inbox_delete_web.py`. Full suite: 1707 passed.

## Deviations
1. Glossary `verwijderen_document` explanation shortened to 206 chars (spec text was 284, existing `test_entry_valid` enforces <= 220). Text: "Een bon of factuur die je nog niet hebt geboekt kun je verwijderen, bijvoorbeeld bij het verkeerde bestand. Bestand en uitgelezen gegevens verdwijnen definitief. Een geboekt document blijft 7 jaar bewaard." Alternative: raise the limit in the test.
2. Info icon sits next to the filename heading in the confirmation card, not in the h1: `test_every_glossary_key_is_used` only detects literal `info("key")` in templates, not `page_header(term=...)`.
3. Spec claim that `store_result`/`store_failure` "already raise DocumentNotFoundError" was not true in practice: the session keeps objects after commit (identity map returns the stale Document), giving an FK IntegrityError (500). Fixed in `extraction_routes._extract_one` with `session.expire_all()` after the extractor returns.
4. `BankFileStorage.remove` raises `DocumentStorageFailedError` (plain Dutch message).
5. Updated existing tests that asserted "no remove/delete API": `tests/documents/test_service.py`, `tests/documents/test_storage.py`, `tests/bank/test_storage.py`, and removed the `post /inbox/1/verwijderen` case from `tests/test_inbox_web.py::test_no_delete_routes` (route now exists).
6. `delete_document` itself calls `session.rollback()` on OSError (besides raising), so the DB is unchanged even if the caller forgets; the route rolls back too.
7. Booked check in list rows uses status only (`nieuw`/`herkend`); the purchase_invoice check lives in `can_delete` (used by the confirm page) and `delete_document`.

## Notes for integrator
- The confirmation GET for a booked document returns 200 with the AC 3 message; POST returns 409 with the same page.
- `_list_page` is imported from `inbox_routes` into `extraction_routes` (private name) for the "deleted meanwhile" page.
- Nothing added to `PAGES` in test_plain_language; the new pages are covered by `assert_plain_language` in `tests/test_inbox_delete_web.py`.
