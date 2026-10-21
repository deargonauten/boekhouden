Status: APPROVED

# Spec: Documenten-inbox (handmatig uploaden van facturen en bonnen)

## 1. Goal and context
Facturen en bonnen (PDF/foto) are the raw material of the bookkeeping. This feature delivers the first half of the "inbox -> boeken -> rapportage" flow:
1. Manual upload of one or more PDF/image files on the existing sidebar page "Inbox" (`/inbox`, currently a placeholder).
2. Content-addressed, never-deleted storage in `data/documents/` (Awr bewaarplicht 7 jaar), with a `document` table.
3. An inbox list with status `nieuw` / `herkend` / `geboekt`, a file viewer route, and duplicate detection by content hash.
4. A domain API that the later features plug into without changes to this design: AI extraction (`nieuw` -> `herkend`), purchase booking (`herkend` -> `geboekt`, link to the journal entry), email intake (`source="email"`), bank reconciliation (looks up documents via the booking link).

Existing conventions to follow: domain code in `app/domain/<area>/` with `__init__.py` public API; SQLAlchemy 2.0 models in `app/models/` (re-exported in `app/models/__init__.py`); domain errors are `LedgerError` subclasses with stable `code` + Dutch `message` (`app/domain/errors.py`, see `RelationError`); thin route handlers (`app/web/*_routes.py`, `_render`, 303 redirects), templates under `app/web/templates/`; glossary in `app/domain/glossary.py` (existing `inbox` entry is reused); Alembic migrations in `migrations/versions/` (latest: `0003_relations`); `Settings.documents_dir` and `ensure_data_dirs` already exist in `app/config.py`; `python-multipart` is already a dependency; test fixtures `client`/`test_settings` in `tests/conftest.py` (the test settings already point `documents_dir` to a tmp path) and the `engine`/`session` pattern in `tests/relations/conftest.py`.

## 2. Non-goals
- No extraction / Claude API / OCR code, no review screen, no booking, no email/IMAP code. Only the hooks (statuses, source, link column, domain functions) that those features will call.
- No delete route, no delete function, no "remove from inbox" and no hide/ignore status (see decision D10). No rename, no editing of the file.
- No HEIC/HEIF support (see D4), no Word/Excel/zip, no password-protected PDF handling, no virus scanning, no thumbnails/preview rendering beyond the browser's native display of the stored file.
- No pagination/search in the list (single user, a few hundred documents per year; list is capped at the 500 newest, see AC 14), no bulk actions, no drag-and-drop widget beyond the native multi-file input.
- No authentication.
- No backup/export (own backlog item), but the layout must stay simple enough for it (D1).

## 3. User stories
- As the owner I can pick one or more invoices/receipts (PDF or photo) from my computer and put them in the inbox in one go, and I see per file whether it worked.
- If I upload a file that is already in the inbox I am told so in plain Dutch and pointed to the existing one; nothing is stored twice.
- If I choose a wrong or too large file I am told what is wrong and what to do (e.g. convert an iPhone HEIC photo to JPEG).
- I see my inbox as a list, newest first, with a status per document (Nieuw / Herkend / Geboekt), can filter by status, and can open the original file to look at it.
- I can trust that nothing I upload is ever deleted (bewaarplicht).
- (Later features) The extraction, booking and email features can add documents, change status and link a booking through the domain API without schema redesign.

## 4. Acceptance criteria

### Storage and data
1. Alembic migration `0004_document_inbox` (down_revision `0003_relations`) creates table `document`, with upgrade and downgrade; `alembic check` shows no drift; `tests/test_migrations.py` head assertion becomes `0004_document_inbox`. The migration does not import `app.models`.
2. Columns of `document`: `id` PK; `sha256` TEXT NOT NULL (64 lowercase hex, UNIQUE index `uq_document_sha256`); `original_filename` TEXT NOT NULL (sanitized display name, max 255 chars); `content_type` TEXT NOT NULL (`application/pdf`, `image/jpeg`, `image/png`, `image/webp`; determined from the file content, see AC 6); `size_bytes` INTEGER NOT NULL (> 0); `status` TEXT NOT NULL default `'nieuw'`; `source` TEXT NOT NULL default `'upload'`; `source_ref` TEXT NULL (free reference of the source, e.g. email Message-ID; unused for uploads); `journal_entry_id` INTEGER NULL FK -> `journal_entry.id` (the booking this document belongs to, set when status becomes `geboekt`); `received_at` DATETIME NOT NULL (moment of upload/receipt); `created_at`, `updated_at` DATETIME NOT NULL. Indexes: `ix_document_status`, `ix_document_received_at`, `ix_document_journal_entry_id`.
3. CHECK constraints (named): `ck_document_status` (`status IN ('nieuw','herkend','geboekt')`), `ck_document_source` (`source IN ('upload','email')`), `ck_document_size` (`size_bytes > 0`), `ck_document_sha256` (`length(sha256) = 64`), `ck_document_booked_link` (`status <> 'geboekt' OR journal_entry_id IS NOT NULL`). (Adding values later is done by a migration in the feature that needs it; allowed values live as constants `DOCUMENT_STATUSES`/`DOCUMENT_SOURCES` in the domain.)
4. Files are stored at `<documents_dir>/<sha256[0:2]>/<sha256>.<ext>` where ext is `pdf|jpg|png|webp` derived from the detected type (never from the user's filename). The sha256 is computed over the exact uploaded bytes. Writing is atomic: write to a temp file in the same directory, `fsync`, then `os.replace`/`link` to the final name; the final file is created with mode 0o444 (read-only). An existing file with the same final name is never overwritten (if a file is already there, e.g. an orphan from a failed earlier insert, its size/hash is verified and it is reused). No code path anywhere deletes or truncates a stored file; there is no delete function in the storage module or the service (test asserts `not hasattr`).
5. The user-supplied filename is only metadata: it is sanitized (basename only, control chars and path separators removed, trimmed, max 255 chars, empty -> `document.<ext>`) and never used to build a filesystem path. Path traversal attempts like `../../x.pdf` store the file under its hash path and the display name `x.pdf`.

### Validation (plain-Dutch errors, all in `app/domain/documents/`)
6. File type is detected from the content (magic bytes), not from the extension or the browser's Content-Type: PDF (`%PDF-` within the first 1024 bytes), JPEG (`FF D8 FF`), PNG (8-byte signature), WebP (`RIFF....WEBP`). Anything else is rejected with `UNSUPPORTED_FILE_TYPE`: "Dit bestandstype kan niet worden verwerkt. Kies een PDF, JPEG, PNG of WebP-bestand." If the content is HEIC/HEIF (`ftyp` box with brand `heic|heix|heif|mif1|hevc`): "Dit lijkt een HEIC-foto (iPhone). Zet de foto om naar JPEG, of stel je camera in op 'Meest compatibel', en probeer het opnieuw."
7. Maximum size 20 MB (20 * 1024 * 1024 bytes, constant `MAX_DOCUMENT_BYTES`). Larger: `FILE_TOO_LARGE`: "Dit bestand is te groot (<x,x> MB). De grens is 20 MB. Maak de PDF kleiner of fotografeer met een lagere resolutie." The route must not read an unbounded body into memory: read the upload in chunks and stop at limit + 1 byte.
8. Empty file (0 bytes): `EMPTY_FILE`: "Dit bestand is leeg. Kies een ander bestand." No file chosen at all (form submitted without files): `NO_FILE_SELECTED`: "Je hebt nog geen bestand gekozen. Kies een PDF of foto van je factuur of bon." (HTTP 422).
9. Validation order: empty -> too large -> type. A rejected file stores nothing (no file, no row).
10. All failures raise `DocumentError(LedgerError)` subclasses with codes `UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE`, `EMPTY_FILE`, `NO_FILE_SELECTED`, `DOCUMENT_NOT_FOUND`, `INVALID_STATUS_TRANSITION`, `DOCUMENT_STORAGE_FAILED` (added to `app/domain/errors.py` with the existing `_error_class` pattern). Messages are shown verbatim, contain no codes/exception text, and each says what to do (a domain test checks all messages following the `tests/domain/test_relations_error_messages.py` pattern). `DOCUMENT_STORAGE_FAILED`: "Het bestand kon niet worden opgeslagen. Controleer of er nog schijfruimte is en of de map data/documents beschrijfbaar is, en probeer het opnieuw."

### Duplicates
11. Uploading bytes whose sha256 already exists never creates a second row or file. The domain call returns a result with `outcome="duplicate"` and the existing document; the UI shows for that file: "<bestandsnaam> staat al in je inbox (geupload op <datum>, status <status>). Het is niet nog een keer opgeslagen." with a link "Bekijk het bestaande document" to `/inbox/{id}`. This is a normal outcome, not an error (not a 4xx on its own). Duplicate detection is by content only (the same invoice with different bytes, e.g. re-scanned, is not detected; that is accepted, later extraction may flag same invoice number + supplier).
12. Two concurrent uploads of identical bytes are safe: the unique index is the backstop; an `IntegrityError` on `sha256` is caught, the session rolled back to the savepoint, and the result is `duplicate` pointing to the winning row. Two identical files in one multi-file request: the first is `created`, the second `duplicate`.

### Inbox UI (Dutch)
13. `/inbox` is served by a real router (`app/web/inbox_routes.py`); the placeholder is not registered for `inbox` (update `LEDGER_KEYS`/skip set in `app/web/routes.py`). `GET /` still redirects to `/inbox`.
14. `GET /inbox` shows (a) an upload form at the top: heading "Factuur of bon toevoegen", a multiple-file input (`accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/*"`), helper text "PDF of foto (JPEG, PNG, WebP), maximaal 20 MB per bestand. Je kunt meerdere bestanden tegelijk kiezen. Bestanden worden bewaard en nooit verwijderd.", button "Toevoegen aan inbox"; (b) status filter links "Alle (n) / Nieuw (n) / Herkend (n) / Geboekt (n)" via `?status=`; unknown value falls back to Alle; (c) a table with columns Bestand (link to detail), Type (PDF / Foto), Grootte (e.g. "1,2 MB"), Toegevoegd op (date + time, `dd-mm-jjjj hh:mm`), Bron (Upload / E-mail), Status (badge). Sorted newest first (`received_at DESC, id DESC`), capped at 500 rows with a plain note when capped. Empty state in plain Dutch: "Je inbox is leeg. Voeg hier de facturen en bonnen toe die je nog moet verwerken. Daarna kun je ze laten uitlezen en boeken." (for a filter with no hits: "Geen documenten met deze status.").
15. `POST /inbox/upload` (multipart, field `files`, multiple): processes each file independently via the domain service; one bad file does not stop the others. Response renders the inbox page (HTTP 200, or 422 when every file was rejected / none chosen) with a result block above the table listing per file: success ("<naam> is toegevoegd aan je inbox."), duplicate (AC 11), or rejection (the `DocumentError` message prefixed with the file name). Successful files are committed even when other files fail. The page is rendered directly (no flash storage); a hint is not needed for refresh behaviour.
16. `GET /inbox/{id}` detail page: file name, type, size, upload date, source, status badge with its plain explanation, SHA-256 shown shortly as "Vingerafdruk van het bestand" (info icon: identical files get the same fingerprint, which is how duplicates are detected), a link "Open origineel bestand" and an embedded view (`<iframe>` for PDF, `<img>` for images, max-width 100%) of `/inbox/{id}/bestand`. If `status == "geboekt"`: link to the booking `/boeken/{journal_entry_id}` (use the existing entry detail route; check its actual path). Unknown id -> 404 page (existing handler). A short note: "Later kun je hier de gegevens laten uitlezen en de factuur boeken." is NOT shown (no promises of unbuilt features); for `nieuw` show only "Nog niet verwerkt."
17. `GET /inbox/{id}/bestand` streams the stored file with the stored `content_type`, `Content-Disposition: inline; filename*=UTF-8''<sanitized name>`, `X-Content-Type-Options: nosniff`, and, for images only, `Content-Security-Policy: sandbox`. PDFs are served WITHOUT a CSP (rework round 1): `sandbox` makes Chrome/Safari refuse to render the built-in PDF viewer, and PDFs are the main use case. Rationale: the stored type comes from magic-byte detection, `nosniff` prevents type confusion, and the app is localhost/single-user. 404 if the row is unknown; if the row exists but the file is missing on disk, 500-class plain Dutch page/message "Het bestand ontbreekt op schijf. Herstel data/documents uit je back-up." (an integrity problem, never silently ignored) and an error is logged.
18. There is NO delete route or button: tests assert `DELETE /inbox/{id}`, `POST /inbox/{id}/verwijderen`, `POST /inbox/{id}/delete` give 404/405.
19. Status can only change through domain functions; there is no web route that changes status in this feature (status badges are read-only). Existing `GET /` and nav item remain.

### Status model (domain, for later features)
20. `app/domain/documents/status.py` (pure) defines `DocumentStatus` constants and `ALLOWED_TRANSITIONS = {nieuw: {herkend, geboekt}, herkend: {geboekt}, geboekt: {}}`; `nieuw -> geboekt` exists so a document can be booked manually without extraction. `geboekt` is final (corrections are made with a storno on the booking, never by reopening the document). `herkend -> nieuw` is deliberately not allowed in this feature (re-extraction is handled by the extraction feature without a status change).
21. Service functions (all flush, never commit; caller owns the transaction): `mark_recognized(session, document_id)` (`nieuw` -> `herkend`), `mark_booked(session, document_id, journal_entry_id)` (`nieuw|herkend` -> `geboekt`, requires an existing journal entry, sets `journal_entry_id`), both bump `updated_at`. An illegal transition raises `INVALID_STATUS_TRANSITION`: "Dit document kan niet van <status> naar <status> worden gezet." followed by an actionable hint ("Een geboekt document blijft geboekt; maak de boeking ongedaan met een stornoboeking als er iets niet klopt."). `mark_booked` with an unknown journal entry raises `JournalEntry`-not-found style error mapped to a `DocumentError` ("Deze boeking bestaat niet.").
22. Ingest API for any source: `add_document(session, storage, content: bytes | BinaryIO, filename: str, *, source: str = "upload", source_ref: str | None = None, received_at: datetime | None = None) -> AddResult` where `AddResult` is a frozen dataclass `(document: Document, outcome: Literal["created","duplicate"])`. The manual upload and the future email intake both use it; validation (AC 6-9) happens inside. Other API: `get_document(session, id)`, `list_documents(session, *, status=None, limit=500) -> list[Document]`, `count_by_status(session) -> dict[str, int]` (all three keys always present), `document_path(storage, document) -> Path`, `open_document(...)`. Status names/labels (`STATUS_LABELS = {"nieuw": "Nieuw", ...}`) live in the domain, not in templates.

### Plain-language requirements (CLAUDE.md)
23. Terms introduced by this feature, each with a glossary entry in `app/domain/glossary.py` (plain phrase, explanation <= 220 chars, no guarded jargon per existing tests):
    - `inbox` (exists; its explanation is extended to mention manual upload: "Hier komen facturen en bonnen binnen die nog verwerkt moeten worden, bijvoorbeeld door ze zelf toe te voegen of uit je mailbox." Keep within 220 chars).
    - `status_nieuw` ("Nieuw", plain: "Nog niet bekeken"): "Het document staat in je inbox maar is nog niet uitgelezen of geboekt."
    - `status_herkend` ("Herkend", plain: "Gegevens uitgelezen, wacht op jouw controle"): "De gegevens van de factuur (leverancier, datum, bedragen) zijn uitgelezen. Controleer ze voordat je boekt."
    - `status_geboekt` ("Geboekt", plain: "Vastgelegd in je administratie"): "Van dit document is een boeking gemaakt. Het document blijft bij de boeking bewaard."
    - `bewaarplicht` ("Bewaarplicht", plain: "Je moet administratie 7 jaar bewaren"): "De wet verplicht je facturen en bonnen 7 jaar te bewaren. Daarom kun je documenten hier niet verwijderen."
    - `vingerafdruk` ("Vingerafdruk van het bestand", plain: "Unieke code van de inhoud"): "Een korte code die bij de inhoud van het bestand hoort. Hetzelfde bestand krijgt altijd dezelfde code, zo ziet het programma dat je iets dubbel toevoegt."
    - `bron` is not a bookkeeping term; no entry. "Upload"/"E-mail" are plain words.
    Detect regexes: `status_*` use `(_NEVER,)` (words too generic; they must be used with `info()` in the status filter and status column header/badge of the new templates); `bewaarplicht` detect `\bbewaarplicht\b`; `vingerafdruk` detect `\bvingerafdruk\b`. Builder adjusts if the existing guard tests demand otherwise, but every new key must be used by a template so the "unused key" test passes without growing `UNUSED_OK`.
24. Every term occurrence on the new pages passes `assert_plain_language`; `/inbox` (empty and filled, with result block) and `/inbox/{id}` are added to `PAGES` in `tests/test_plain_language.py`. The word "Inbox" in the nav keeps its existing sub-line.
25. Suggested defaults: none to choose (no accounts/VAT/periods here); the form has nothing to pre-fill. State this in the template-free test: the upload form has exactly one required action (pick files and press the button).
26. Status badges show the plain phrase on hover/info icon, e.g. "Herkend (i)" -> "Gegevens uitgelezen, wacht op jouw controle".

## 5. Technical approach

### Package layout
```
app/domain/documents/__init__.py     public API
app/domain/documents/validation.py   pure: sniff_type(bytes) -> DetectedType | raises, check_size, sanitize_filename, MAX_DOCUMENT_BYTES, ALLOWED types, format_size
app/domain/documents/status.py       pure: statuses, labels, ALLOWED_TRANSITIONS, check_transition
app/domain/documents/storage.py      FS only: DocumentStorage(root: Path): path_for(sha256, ext), write(bytes/stream) -> StoredFile, exists/open; no delete
app/domain/documents/service.py      DB+storage: add_document, get/list/count, mark_recognized, mark_booked
app/models/documents.py              Document model (re-export in app/models/__init__.py)
migrations/versions/0004_document_inbox.py
app/web/inbox_routes.py              router for /inbox*
app/web/templates/inbox/{list,detail,_results}.html
```
`DocumentStorage` is constructed per request from `request.app.state.settings.documents_dir` (via a small dependency `get_storage`); tests override it with the tmp `documents_dir` from `test_settings`.

### Flow: add_document
1. Read bytes into memory (<= 20 MB + 1 sentinel; the route reads UploadFile in 1 MB chunks and aborts at the limit; domain also checks `len`).
2. Validate empty/size/type (pure). Compute sha256.
3. `SELECT` by sha256: found -> `duplicate`.
4. Otherwise write the file via storage (atomic, idempotent), then `INSERT` inside `session.begin_nested()`; on `IntegrityError` for sha256 -> `duplicate` (AC 12). Flush, no commit. If the DB transaction is later rolled back by the caller the file stays (orphan, harmless: content-addressed, reused on the next upload of the same bytes; never deleted by design). The route commits after each file so partial success is preserved.
5. `received_at` defaults to `datetime.now()` (naive local time like the rest of the app, check `ledger` conventions), `source="upload"`.

### Future plug-in points (documented, not built)
- Extraction: reads file via `document_path`, then calls `mark_recognized`; stores its results in its own table keyed by `document.id` (no extraction columns here).
- Booking: calls `mark_booked(session, doc_id, entry.id)` in the same transaction as the journal entry posting; `journal_entry_id` makes "which document belongs to this booking" a plain join (bewaarplicht: documents kept with the booking).
- Email intake: `add_document(..., source="email", source_ref=message_id)`; duplicate result lets it skip silently.
- Bank reconciliation: joins via `journal_entry_id`.
Because one document could in theory justify several bookings (or several documents one booking), the link is deliberately a simple nullable FK on the document side now; if many-to-many is needed it is a later migration.

### Web
`inbox_routes.py` mirrors `relations_routes.py`: handlers parse the multipart form, call the domain service per file, commit, and render. No validation or storage logic in handlers. `UploadFile` is read chunked; the stream is handed to the domain as bytes. Add minimal CSS (status badges, result block) to `app/web/static/app.css`, reusing `table-wrap`, `data`, `btn`. Use `partials/_info.html` (`term_label`, `info`).

### Error handling
Domain errors map to messages in the result block; storage `OSError` is wrapped into `DOCUMENT_STORAGE_FAILED` (HTTP 500 only if every file fails for that reason; otherwise listed per file). Missing-on-disk file at view time: AC 17.

## 6. Work breakdown
Part A - Domain pure logic + errors (no DB, no FS). Owns `app/domain/documents/validation.py`, `app/domain/documents/status.py`, `app/domain/errors.py` (document codes + `DocumentError`), `tests/domain/test_documents_validation.py`, `tests/domain/test_documents_status.py`, `tests/domain/test_documents_error_messages.py`. No dependencies. Provides `sniff_type`, `sanitize_filename`, `MAX_DOCUMENT_BYTES`, `format_size`, `ALLOWED_TRANSITIONS`, `STATUS_LABELS`, `check_transition`.
Part B - Storage + model + migration + service. Owns `app/domain/documents/storage.py`, `service.py`, `__init__.py`, `app/models/documents.py`, `app/models/__init__.py` (one-line export), `migrations/versions/0004_document_inbox.py`, `tests/documents/` (conftest, test_storage, test_service, test_schema), `tests/test_migrations.py` (head update). Depends on A's interfaces (agree signatures from sections 4-5 up front; may stub).
Part C - UI + glossary. Owns `app/web/inbox_routes.py`, `app/web/templates/inbox/*`, `app/web/routes.py` (inbox wiring, skip set), `app/domain/glossary.py` (new terms + inbox text), `tests/domain/test_glossary.py` (REQUIRED list), `tests/test_inbox_web.py`, `tests/test_plain_language.py` (PAGES), CSS. Depends on B's service/storage API and A's errors; integration points are `add_document`/`AddResult`, `DocumentError.message`, `STATUS_LABELS`.
Integration points: `app/domain/documents/__init__.py` exports (B owns, A adds its names); `app/domain/errors.py` (A only); `app/models/__init__.py` (B only); `app/web/routes.py` (C only).

## 7. Test strategy
Tests first for validation, hashing/storage and the status machine (they protect legally required records).
- Validation unit tests: magic bytes for PDF (also with leading garbage < 1024 bytes), JPEG, PNG, WebP accepted; a `.pdf` filename with JPEG content detected as JPEG; a text file renamed `.pdf` rejected; HEIC rejected with the HEIC message; empty; exactly 20 MB accepted, 20 MB + 1 rejected; message formats (size in MB with comma); `sanitize_filename` table (traversal, slashes, backslashes, control chars, unicode, 300-char name, empty).
- Storage tests: path layout `ab/abcdef....pdf`; atomic write leaves no temp files; read-only mode; existing identical file reused, existing file with wrong content not overwritten (raises `DOCUMENT_STORAGE_FAILED`); no `delete`/`remove` attribute; unwritable root -> `DOCUMENT_STORAGE_FAILED`.
- Service tests (session fixture + tmp storage): created row fields (sha256 matches `hashlib`, size, content_type, status `nieuw`, source `upload`); duplicate returns existing and creates no second row/file; two identical in sequence; simulated IntegrityError race path; rejected file leaves no row/file; `list_documents` ordering and status filter; `count_by_status` has all keys; transitions: allowed paths, `geboekt` final, illegal ones raise with message; `mark_booked` requires an existing entry and sets the link; `updated_at` bump; service does not commit (rollback discards row).
- Schema tests: CHECK constraints (status, source, size, booked-needs-link), unique sha256, FK to `journal_entry`; migration upgrade/downgrade/check.
- Web tests (`client` fixture; PDF/JPEG/PNG fixtures are tiny byte strings): empty-state inbox; upload single valid PDF (appears in list, file exists at hash path, content equal); multi-file upload with one good, one duplicate, one bad type (200, three messages, good one stored); all-bad -> 422; no files -> 422 with message; oversize -> message (use a monkeypatched small limit); duplicate message links to existing; filter by status incl. unknown value; detail page and `/bestand` headers (`nosniff`, CSP sandbox on images only and absent on PDFs, content type, inline); 404 for unknown id; missing-on-disk file shows the integrity message; no delete routes; `/inbox` no longer renders the placeholder; counts in filter links.
- Plain-language: new pages in `PAGES`, new glossary keys valid and used, existing pages unaffected.
- Full existing suite stays green.

## 8. Risks and decisions made
- D1 Storage layout `sha256[0:2]/sha256.ext` under `data/documents/`: content-addressed per CLAUDE.md, fan-out keeps directories small, extension only for convenience when browsing/backing up (the DB holds the truth). Files are read-only and never deleted.
- D2 SHA-256 of raw bytes is the identity. Same bytes = same document; re-scans are different documents. Accepted; semantic duplicate detection (invoice number + supplier) belongs to extraction/booking.
- D3 Type detection by magic bytes, not by extension/Content-Type, because browsers and mailers send wrong types; the stored `content_type` comes from this detection and is what the viewer serves.
- D4 Accepted types: PDF, JPEG, PNG, WebP. WebP is cheap (magic bytes) and supported by the Claude API vision input. HEIC is rejected with a helpful message: the Claude API does not accept HEIC and decoding it needs extra native libraries, which would break "no Docker, simple local install". Revisit with extraction if iPhone photos are a common case.
- D5 20 MB limit: the Claude API request limit for files is around that size and invoices are far smaller; also bounds memory since uploads are read into memory to hash.
- D6 Status stored as TEXT with CHECK (SQLite has no enums); transitions enforced in the domain, not in handlers. `geboekt` requires a `journal_entry_id` (CHECK) so a document can never claim to be booked without a booking. `nieuw -> geboekt` allowed for manual booking without extraction.
- D7 `source` limited to `upload|email` now; `bank` or others can be added by the migration of the feature that needs it. `source_ref` is generic for the email Message-ID.
- D8 Link to booking is `document.journal_entry_id` (nullable FK) rather than a link table: simplest thing that supports "documents kept with the booking" and reconciliation joins; a many-to-many can come later without data loss.
- D9 Service flushes but never commits (as in relations): the later booking flow must be able to roll back a whole approval. Orphaned files after a rollback are acceptable and reused by hash (nothing is ever deleted).
- D10 No way to remove or hide a wrongly uploaded document (e.g. a private photo). Conscious: bewaarplicht and append-only principle; an "genegeerd/niet relevant" status would be a business decision for the extraction/booking feature (a hidden status still keeps the file). Documented here so it is not forgotten.
- D11 Result display is rendered in the POST response instead of redirect + flash, to avoid introducing session/flash infrastructure for one feature; trade-off: browser refresh re-posts the form (duplicates are harmless thanks to hash detection).
- D12 The file viewer serves user-supplied content from the app's origin; mitigated by detected content type and `nosniff`; images additionally get `Content-Security-Policy: sandbox`. PDFs are deliberately unsandboxed because `sandbox` breaks the browser PDF viewer (Chrome/Safari); a restrictive `object-src`/`plugin-types` CSP was not adopted since it cannot be verified across browsers. The app is localhost-only and single-user.
- D13 The glossary `status_*` entries use no auto-detect (words too generic) and are attached by explicit `info()` calls in the new templates, same approach as `klant`/`leverancier` in the relations spec.
