Status: APPROVED

# Spec: delete-unbooked-documents (ongeboekte inbox-documenten verwijderen)

## 1. Goal and context
The owner can really delete an uploaded invoice or receipt from the inbox as long as it is not booked (status `nieuw` or `herkend`): the `document` row, its extraction (`invoice_extraction` + `invoice_extraction_line`) and the file under `data/documents/`. Typical use: a wrong, duplicate or unreadable upload. Booked documents can never be deleted; the screen says so in plain Dutch and points to the stornoboeking.

This is a deliberate user decision that changes the rule "attachments ... never deleted" in CLAUDE.md. The bewaarplicht (7 years) applies to administration that is part of a booking; an unbooked inbox upload is not yet administration. The rule is amended, not dropped (see AC 14).

Facts found in the code:
- `document.sha256` is UNIQUE (`uq_document_sha256`), and the stored path is `<sha[0:2]>/<sha>.<ext>` with ext derived from the content type. So at most one document row points to a given file and "only delete the file if no other record shares it" is a defensive check (it must still be implemented and tested, because another row could in future share the file, e.g. through a different source).
- FKs pointing to `document.id`: `invoice_extraction.document_id` (UNIQUE) and `purchase_invoice.document_id`. `invoice_extraction_line.extraction_id` points to the extraction. `PRAGMA foreign_keys=ON` is set, so a delete in the wrong order fails. No DB triggers exist on `document`, `invoice_extraction`, or its lines (triggers exist only on journal/period/fiscal_year tables, migration 0002). No migration is needed.
- `supplier_default` (learned account per leverancier) is keyed on `contact_id` + `account_id`, has no reference to a document or extraction. Contacts created or linked during review also stay. Both are untouched on purpose (the learning stays valuable).
- Bank import files live in a separate `BankFileStorage` (`data/bank/`), a subclass of `DocumentStorage`. It must stay non-deletable.
- Extraction runs in `extraction_routes._extract_one` between two commits (the file is read in `build_request`, the extractor runs without a write lock, then `store_result` / `store_failure` write). A delete may therefore happen while an extraction is in flight.

## 2. Non-goals
- Deleting bank import files, bank transactions, journal entries, booked documents or booked purchase invoices.
- Soft-delete, trash bin, undo, audit log of deleted documents.
- Bulk delete (one document at a time).
- Deleting contacts that were created from the extraction, or touching `supplier_default`.

## 3. User stories
- As owner I upload the wrong file and remove it from the inbox so the list stays clean.
- As owner I am asked to confirm in plain Dutch before anything is removed, and told it cannot be undone.
- As owner I try to delete a booked document and am told why not and what to do (stornoboeking).

## 4. Acceptance criteria

### Behaviour
1. `delete_document(session, storage, document_id)` in `app/domain/documents/service.py` deletes, in one transaction: all `invoice_extraction_line` rows of the document's extraction, the `invoice_extraction` row, the `document` row; then the stored file. It flushes but never commits (like the rest of the service); the route commits.
2. Allowed only when ALL hold: `status in (nieuw, herkend)`, `journal_entry_id IS NULL`, and no `purchase_invoice` row has this `document_id`. The check happens inside the delete function (not only in the UI), on freshly read data in the same transaction.
3. Otherwise raise `DocumentDeleteNotAllowedError` (subclass of `DocumentError`, code `DOCUMENT_DELETE_NOT_ALLOWED`) with message: "Dit document is al geboekt en kan niet worden verwijderd, want het hoort bij je administratie (bewaarplicht). Klopt de boeking niet? Maak dan een stornoboeking: open de boeking en kies 'Stornoboeking maken'. Het document blijft dan bij de boeking bewaard." Nothing is changed (no rows, no file).
4. Unknown id: `DocumentNotFoundError` (existing message); route answers with the existing 404 page.
5. File removal: the file is removed only if no other `document` row has the same `sha256` (and ext). If another row shares it, the file stays and the delete still succeeds. If the file is already missing on disk, the delete still succeeds (nothing to remove; log a warning, no error to the user). Empty shard directory `<sha[0:2]>/` is removed if empty (best effort).
6. Storage gets a new explicit method `DocumentStorage.remove(sha256, ext) -> bool` (returns whether a file was removed; handles the read-only `0o444` mode, unlinks only the exact computed path, never globs, validates `sha256` is 64 hex chars and ext is allowed). `BankFileStorage` overrides `remove` to raise (bank files stay undeletable). The module docstring of `storage.py` is updated: deletion exists only through `remove`, used only by `delete_document`.
7. Order inside the transaction: delete DB rows and flush (this takes the SQLite write lock, so no concurrent insert can slip in), re-check no other row shares the sha, then remove the file, then the route commits. If file removal raises an OSError, roll back and show: "Het bestand kon niet worden verwijderd. Controleer of de map data/documents beschrijfbaar is en probeer het opnieuw." (`DocumentStorageFailedError`-style, nothing deleted from the database).
8. Concurrent extraction: `store_result` / `store_failure` for a document that was deleted meanwhile already raise `DocumentNotFoundError`. The extraction routes (`/uitlezen`, `/uitlezen-alles`, and the review/save routes) must turn that into a plain message ("Dit document is ondertussen verwijderd. Ga terug naar je inbox.") instead of a 500, and `uitlezen-alles` continues with the next document. Rolling back the session on that error is required.
9. The owner's `supplier_default` rows, contacts, accounts and all other tables are untouched (tested by row counts before/after).

### UI (CLAUDE.md "usable without bookkeeping knowledge")
10. Confirmation page `GET /inbox/{id}/verwijderen` (works without JavaScript; also reachable from the drawer and the detail page). Title "Document verwijderen?". Text: "Je staat op het punt <bestandsnaam> te verwijderen. Het bestand en de uitgelezen gegevens worden definitief gewist. Dit kun je niet ongedaan maken. Upload het bestand later opnieuw als je je bedenkt." Buttons: "Ja, verwijderen" (danger style, `POST /inbox/{id}/verwijderen`) and "Annuleren" (back to the document). For `herkend` documents with a nakijk-result add: "De uitgelezen gegevens (leverancier, bedragen, regels) gaan ook verloren."
11. A "Verwijderen" button (secondary/danger, with `bestand`-style icon if available) appears on the document detail page, in the drawer (`_detail_body.html`) and per row in the inbox list actions column, only for `nieuw` and `herkend`. For `geboekt` the button is replaced by a hint: "Dit document is geboekt en kan niet worden verwijderd." with the term `bewaarplicht` info icon.
12. `GET`/`POST` on a booked document renders the confirmation/detail page with the AC 3 message as an alert (status 409 for POST, 200 for the GET page which shows the message instead of the confirm button). After a successful delete: redirect 303 to `/inbox?melding=verwijderd`, showing the success notice "Het document is verwijderd."
13. Existing texts that claim files are never deleted are corrected: `inbox/list.html` upload hint and `inbox/_detail_body.html` hint become "Een geboekt document wordt altijd bewaard (bewaarplicht). Een document dat nog niet is geboekt kun je verwijderen." The same sentence variants are used in both places. `bank/upload.html` stays unchanged (bank files are still never deleted). Docstrings in `models/documents.py` ("Never deleted") and `service.py` module docstring are corrected.
14. CLAUDE.md is amended. The Decisions line "attachments stored under `data/documents/` (content-addressed, never deleted)" becomes: "attachments stored under `data/documents/` (content-addressed). Never deleted once linked to a booking; the only exception is an unbooked inbox document (status nieuw/herkend) that the user explicitly deletes, which removes the document, its extraction data and its file. Bank import files are never deleted." The Domain rules append-only line stays and gets: "(documents of booked entries are kept with the booking)". The builder makes exactly this edit.
15. Glossary (`app/domain/glossary.py`): update the `bewaarplicht` entry text from "Daarom kun je documenten hier niet verwijderen." to "Daarom kun je een geboekt document hier niet verwijderen. Een document dat nog niet is geboekt (nieuw of herkend) mag je wel weggooien." New term `verwijderen_document`: label "Document verwijderen", short "Definitief wissen, alleen vóór het boeken", explainer: "Een bon of factuur die je nog niet hebt geboekt kun je helemaal verwijderen, bijvoorbeeld als je het verkeerde bestand hebt gekozen. Het bestand en de uitgelezen gegevens verdwijnen definitief. Zodra een document is geboekt hoort het bij je administratie en blijft het 7 jaar bewaard." The info icon with this term sits next to the confirmation title. No other new bookkeeping terms.
16. All error and warning texts are plain Dutch as given above; no codes or exceptions shown. The existing `test_plain_language` rules must still pass.

## 5. Technical approach
- Domain (`app/domain/documents/`): `delete_document` + `can_delete(session, document) -> bool` (used by templates through a Jinja global or a precomputed flag so the list does not N+1: compute the set of booked document ids with one query for the shown rows, or rely on `status == 'geboekt' or journal_entry_id` for the UI and let `delete_document` stay authoritative for the purchase_invoice check; builder chooses, the purchase check lives only in the domain). Export through `app/domain/documents/__init__.py`. New error in `app/domain/errors.py`: `DOCUMENT_DELETE_NOT_ALLOWED`. `documents` must not import `purchase` at module level (purchase imports documents); query `PurchaseInvoice` with a late import, or a lightweight SQL `exists` on the table via the model imported inside the function.
- Delete order: lines -> extraction -> document (FK order, foreign_keys=ON). Use `delete()` statements, not ORM relationship cascades (the `lines` relationship is viewonly).
- Storage: `DocumentStorage.remove` as in AC 6. Path computed only from validated sha/ext, resolved to stay under `root`.
- Web (`app/web/inbox_routes.py`, thin): `GET/POST /inbox/{document_id:int}/verwijderen`, templates `inbox/delete.html` (+ buttons in `_detail_body.html`, `detail.html` if needed and `list.html` actions column). Route calls domain, commits, maps `DocumentError` to messages. Register routes before any catch-all; `:int` converter is already used.
- Extraction routes: catch `DocumentNotFoundError` per AC 8.
- Race note: a re-upload of identical bytes between the file check and the unlink is theoretically possible; the DB write lock taken by the delete before unlink and the sha re-check make it practically impossible for a single-user local app. Accepted.

## 6. Work breakdown
Single part (small feature), one builder owns:
- `app/domain/documents/service.py`, `__init__.py`, `storage.py`, `app/domain/bank/storage.py` (override only), `app/domain/errors.py`, `app/domain/glossary.py`
- `app/web/inbox_routes.py`, `app/web/extraction_routes.py` (AC 8 only), templates under `app/web/templates/inbox/`
- `app/models/documents.py` docstring, `CLAUDE.md` (AC 14)
- tests (below)

## 7. Test strategy (tests first for the domain parts)
Domain (`tests/documents/test_delete.py`, use the existing document/extraction fixtures):
- delete `nieuw` doc without extraction: row and file gone.
- delete `herkend` doc with extraction + 3 lines: all three tables empty for that doc; other documents' rows and files untouched.
- `geboekt` doc (journal entry linked): `DocumentDeleteNotAllowedError`, row, extraction and file still present.
- doc with a `purchase_invoice` but (artificially) status `herkend`: refused.
- unknown id: `DocumentNotFoundError`.
- file shared by another row (insert a second row with same sha only possible by dropping the unique index in the test, or by monkeypatching the shared-check helper): file kept, row deleted.
- file missing on disk: delete succeeds.
- storage `remove`: removes read-only file, returns False when absent, rejects bad sha/ext; `BankFileStorage.remove` raises and leaves the file.
- `supplier_default`, contact and account row counts unchanged after deleting a document whose extraction linked a contact.
- OSError on unlink: session rolled back, rows still there (monkeypatch `Path.unlink`).
- service never commits (rollback after delete restores rows).
Web (`tests/test_inbox_web.py` or new `tests/test_inbox_delete_web.py`):
- GET confirmation page for nieuw shows filename, warning text and buttons; for geboekt shows the storno message and no confirm button.
- POST nieuw: 303 to `/inbox?melding=verwijderd`, document no longer listed, `/inbox/{id}` is 404, file gone.
- POST geboekt: 409, message with "stornoboeking", row and file intact.
- POST unknown id: 404.
- Buttons present for nieuw/herkend in list and detail, absent for geboekt; hint texts updated, old "nooit verwijderd" text gone from inbox pages.
- Extraction of a document deleted meanwhile (delete between build and store, simulated with a fake extractor that deletes the document): plain message, no 500; `uitlezen-alles` continues.
- Glossary: `verwijderen_document` exists and renders; `test_plain_language` and `test_info_component` pass.
- CLAUDE.md contains the exception sentence (simple string test is optional).
Full suite `.venv/bin/python -m pytest -q` stays green (baseline 1665 passed).

## 8. Risks and decisions made
- Decision: hard delete, no soft-delete (user decision). Document content is not recoverable; hence a separate confirmation page.
- Decision: confirmation is a server-rendered page rather than a JS dialog: works without JS, testable, matches existing pages.
- Decision: allowed statuses are exactly `nieuw` and `herkend`; "booked" is also detected through `journal_entry_id` and `purchase_invoice`, so inconsistent data can never delete administration. DB FK on `purchase_invoice.document_id` is a second safety net.
- Decision: `supplier_default` and contacts are untouched (learning is per leverancier, not per document).
- Risk: delete during extraction -> handled by AC 8; the in-flight extractor result is discarded (cost: one wasted API call).
- Risk: removing a file that another record needs -> sha re-check (AC 5, 7).
- Risk: a deleted document can be uploaded again later; since the unique sha row is gone it is treated as new. Intended.
- Risk: future features that link a document to something else (e.g. bank reconciliation) must extend `delete_document`'s booked check; noted in the function docstring.
