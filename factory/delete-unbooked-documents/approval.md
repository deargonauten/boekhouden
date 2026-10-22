VERDICT: APPROVE

## Reasoning
The process was followed: spec approved, a single build part (round 1), round-1 reviews (security-code and ux-ui, both REWORK), a fix round (round 2, app-wide same-origin guard plus booked-page storno explanation), and a combined round-2 review that returned PASS and resolved both blocking findings. Two review rounds were used, which is the maximum. The orchestrator reports 1717 passed, 1 deselected; I did not rerun the suite.

I walked the acceptance criteria against the code. The domain rules, storage, CLAUDE.md amendment, glossary entry, plain-Dutch hint texts and the confirmation/booked-document flow are all present. The deviations below are small and documented by the builder or the fix round. None of them weakens the safety rules: booked documents remain undeletable, the file is only removed after a re-check, and the foreign-origin POST is blocked. The remaining open points are cosmetic (nice-to-haves) and do not block shipping.

## Acceptance criteria check (met / not met each)
1. `delete_document` in `service.py`: deletes lines, then extraction, then document, in one transaction, then the file; flushes, never commits (route commits). **Met.**
2. Allowed only for `nieuw`/`herkend`, no `journal_entry_id`, no `purchase_invoice`; checked inside the function on a freshly loaded row (`populate_existing=True`). **Met.**
3. `DocumentDeleteNotAllowedError` (`DOCUMENT_DELETE_NOT_ALLOWED`, subclass of `DocumentError`); nothing changed on refusal. **Met, with wording deviation:** the round-2 fix inserted "Maak de boeking eerst ongedaan (storno):" into the message, so it is not the literal AC 3 text. The change is an intentional plain-language improvement from the UX review and is accepted.
4. Unknown id raises `DocumentNotFoundError`, route answers 404. **Met.**
5. File removed only when no other row shares sha256+content_type; missing file is a warning, not an error; empty shard dir removed best effort. **Met.**
6. `DocumentStorage.remove(sha256, ext) -> bool`: validates sha and ext, computes exact path, checks it stays under root, chmods 0o644 before unlink, no globbing. `BankFileStorage.remove` raises. **Met.** Module docstring updated (per builder report; not re-verified line by line).
7. Order: delete and flush (takes the write lock), re-check shared, then remove file; OSError gives the required Dutch message, rolls back, and the database is unchanged. **Met.**
8. Extraction routes (`/uitlezen`, `/uitlezen-alles`, review save) catch `DocumentNotFoundError` with the required plain message; `uitlezen-alles` continues; `session.expire_all()` added after the extractor returns. **Met.** The builder found the spec's premise ("store_* already raise") was not true in practice (stale identity map leads to FK IntegrityError, a 500) and fixed it in `_extract_one`. This is a sound deviation.
9. `supplier_default`, contacts, accounts and other tables untouched. Delete code only touches the three/lines tables. **Met** (tests per builder report).
10. `GET /inbox/{id}/verwijderen` confirmation page, title "Document verwijderen?", required text, "Ja, verwijderen" (danger, POST) and "Annuleren", herkend extra sentence. **Met** (`inbox/delete.html` checked).
11. Delete button in list actions column, `_detail_body.html` (drawer and detail), only for nieuw/herkend; geboekt shows the hint with bewaarplicht info icon. **Met.** Nice-to-have: the list row shows "Bewaard (bewaarplicht)" without an info icon (round-2 suggestion, not blocking).
12. Booked GET shows the message instead of the confirm button; booked POST returns 409 with the message; success redirects 303 to `/inbox?melding=verwijderd`. **Met.** The code uses 500 only for the storage-failure branch.
13. Hint texts in `list.html` and `_detail_body.html` updated to the required wording; `bank/upload.html` unchanged; `models/documents.py` docstring corrected. **Met.** Service module docstring corrected per builder report.
14. CLAUDE.md amended. Verified line 9 matches the required sentence exactly, and line 15 carries "(documents of booked entries are kept with the booking)". **Met.**
15. Glossary: `bewaarplicht` text updated to the required wording; `verwijderen_document` added and used by the confirmation page info icon. **Met, with deviation:** the explanation text was shortened to fit the existing 220-character limit enforced by `test_entry_valid` (the spec text was about 284 characters). The shortened text keeps the key points (deleted permanently, booked documents kept 7 years) but drops the sentence "Zodra een document is geboekt hoort het bij je administratie". The builder chose to shorten rather than raise the test limit. Acceptable; a human may prefer the full sentence with a raised limit.
16. Plain-Dutch errors and warnings; no raw exceptions or codes shown. `test_plain_language` and `test_info_component` are reported green. **Met.**

Section 7 test strategy: the builder reports domain tests (`tests/documents/test_delete.py`) and web tests (`tests/test_inbox_delete_web.py`) covering the listed cases, including unlink-OSError rollback and the foreign-origin POST. Not rerun, per instruction.

## Outstanding issues
- Non-blocking (round-2 nice-to-have): `list.html` booked row hint lacks `info("bewaarplicht")`.
- Non-blocking (round-2 nice-to-have): `test_service_never_commits` does not assert that a rollback after a successful delete cannot restore the file. This is a documentation/test gap, not a behaviour bug, since the file is removed only after the flush.
- Residual (accepted for a local single-user app): `SameOriginMiddleware` allows unsafe requests that carry neither `Sec-Fetch-Site` nor `Origin`. Modern browsers always send one of these on cross-site POSTs, so the risk is limited to very old browsers. The guard is also app-wide, so every POST route now passes through it.
- Neither review round did visual verification in a browser; both reviewers worked from code and test results.
- Spec text deviations (AC 3 wording, AC 15 glossary length) listed above.

## What the human should look at (if HUMAN_REVIEW)
Not required for this verdict. Optional: open `/inbox` in the browser, delete one unbooked upload, and check the confirmation page and the booked-document message for tone and readability, since no visual check was done.

STATUS: DONE
