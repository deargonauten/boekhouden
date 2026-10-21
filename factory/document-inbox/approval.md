VERDICT: HUMAN_REVIEW

## Reasoning
Process: spec approved, parts A/B/C built, integrated, one review round run (code, security, ui, ux, all PASS), no REWORK findings. `.venv/bin/pytest -q`: 657 passed. `alembic check`: no drift. Code spot-check (inbox_routes.py, detail.html, storage/service grep): thin handlers, chunked read capped at limit+1, commit per file, no delete/unlink of stored files (only own temp file), no delete routes.

Everything in the spec is implemented and tested. I choose HUMAN_REVIEW only because two items need a human look or decision (below), one of which may break a core viewing feature in Chrome and cannot be verified without a browser.

Process note: the Part C build report (factory/document-inbox/build/round-1/part-c.md) is missing; only part-a.md and part-b.md exist (the Part A/B reports are noted as uncommitted worktree files). Part C's work is in the diff (commit 7c2befb) and covered by tests, so this is a paperwork gap, not a delivery gap.

## Acceptance criteria check
1-3 (migration 0004, columns, named CHECKs, head test, no drift): met (alembic check clean, schema tests pass).
4-5 (hash-path storage, atomic, 0o444, never overwrite, no delete, filename sanitising): met.
6-10 (magic-byte detection, HEIC message, 20 MB, empty/no-file, order, error classes, plain-Dutch messages): met.
11-12 (duplicates, IntegrityError race, same-request duplicates): met.
13 (real router, placeholder unregistered): met.
14 (list page, filters, table, cap, empty states): met.
15 (multi-file upload, per-file results, 200/422/500): met.
16 (detail page): met functionally. Minor: for `herkend`/`geboekt` only the info icon follows the badge (no visible sentence; `nieuw` shows "Nog niet verwerkt.", as the spec asks).
17 (file route headers, missing-on-disk page): met by tests and code. Whether it renders in the browser: see below.
18-19 (no delete route, no status-changing route): met.
20-22 (status machine, service API, ingest API): met.
23-24 (glossary entries, plain-language tests, PAGES): met.
25: met (nothing to pre-fill).
26 (badge hover/explanation): partially met. The list-table badge and the Status column header have no own explanation; the info icons are in the filter row and on the detail page. Nice-to-have, not blocking.

## Outstanding issues (none blocking by themselves)
- Part C build report missing (see above).
- AC 26 gap: list-table badge has no `title=` with the plain phrase; Status column header has no info icon.
- Wording: "geupload" (per spec) instead of "toegevoegd"/"geüpload".
- Oversize message shows "20,0 MB" even for a 100 MB file (only limit+1 bytes are read); the message is still correct.
- `request.form()` spools uploads to temp disk before the cap applies; no CSRF/Origin check on POST /inbox/upload (add-only, localhost, low impact).
- `--success` CSS token undefined (hard-coded fallback, not tuned for dark mode).
- pysqlite SAVEPOINT workaround (no-op UPDATE in add_document): works, covered by tests; cleaner to fix globally in app/db.py later.
- Naive UTC timestamps shown as-is, so times may display as UTC instead of local time.

## What the human should look at
1. Content-Security-Policy: sandbox versus Chrome's PDF viewer (unverified, reviewers flagged it independently). Chrome typically refuses to render PDFs in sandboxed documents, and I believe this also applies when the PDF is opened top-level in a tab, so the "Open origineel bestand" fallback link may be blank too. The result would be that PDF invoices (the main use case) cannot be viewed in the app. Please open `/inbox/{id}` with a real PDF in Chrome and Safari. If it is blank, options are: serve PDFs without `sandbox` (keeping `nosniff`, detected content type and magic-byte validation; PDF-embedded script runs in the PDF viewer, not as HTML in the app origin), use `Content-Disposition: attachment` for the fallback link, or an `<object>`/pdf.js viewer. This needs a product/security decision that deviates from AC 17/D12.
2. Decision D10: a wrongly uploaded document (e.g. a private photo, a wrong file) can never be removed or hidden, because of the 7-year bewaarplicht and the append-only principle. This is a conscious spec decision, and legally defensible for real invoices. For a non-invoice mistaken upload it is harsh, with no escape. The spec defers a "genegeerd/niet relevant" status to the extraction/booking feature. Decide whether that is acceptable or a hide-status should be scheduled soon (put it on backlog.md). The UI states clearly that files are never deleted.
3. Optionally glance at the list and detail pages for visual feel (not run by the reviewers; the UI review was code-only).

STATUS: DONE
