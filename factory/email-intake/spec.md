Status: APPROVED

# Email intake (IMAP -> inbox)

## Goal and context
Invoices and receipts often arrive by mail. The user points a dedicated mailbox (for example `facturen@...`, also the address to forward bills to) at the app. The app fetches new mails over IMAP, extracts every PDF/image attachment (also inside forwarded mails, `message/rfc822` or `.eml` attachments, nested), stores them content-addressed through the existing `add_document(..., source="email")`, and they show up in the Inbox as status `nieuw`, source label "E-mail" (already in `SOURCE_LABELS`). From there the existing flow applies (uitlezen, nakijken, boeken).

Existing building blocks (do not change their behaviour):
- `app/domain/documents/service.add_document(session, storage, content, filename, source=, source_ref=, received_at=)` validates size (20 MB) and sniffs type (pdf/jpg/png/webp, by content), dedupes on `Document.sha256` (unique), returns `AddResult(document, "created"|"duplicate")`. It never commits; the caller owns the transaction. `documents.source` already allows `'email'`, `source_ref` is a free string column. No schema change to `document` is needed.
- Settings come from `app/config.Settings` (pydantic-settings, `.env`), `.env.example` documents them.
- Secrets live only in `.env` (gitignored), like `ANTHROPIC_API_KEY`.
- Latest Alembic revision is `0014_btw_aangifte`.

## Non-goals
- No sending mail, no OAuth/XOAUTH2 (app-password / plain LOGIN over TLS only), no plaintext (non-TLS) IMAP, no STARTTLS, no POP3.
- No editing of credentials in the UI (they are read from `.env`; the UI shows status only and explains what to put in `.env`).
- No rendering of the mail body (HTML/text) into a PDF; a mail without PDF/image attachment stores nothing.
- No DOCX/XLSX/ZIP/HEIC extraction (reported as skipped).
- No deleting of documents, and no deleting of mails on the server (mails are moved or marked, never expunged by us).
- No auto-extraction (AI uitlezen) after intake; the user triggers it as today.
- No multi-mailbox support.

## User stories
1. As the owner I put IMAP settings in `.env` once, press "Nu ophalen" in the Inbox and see the invoices from my mailbox appear as new documents.
2. As the owner I can let the app check the mailbox every N minutes without thinking about it.
3. As the owner I forward a supplier mail (with the invoice attached, or the original attached as .eml) and the invoice is still found.
4. As the owner I never get the same invoice twice, however often it is mailed or fetched.
5. As the owner I get a plain-Dutch explanation when the mailbox is not set up, the login fails, or a mail could not be processed, and I know what to do.

## Configuration (all via `.env` / environment, never committed)
Added to `Settings` and `.env.example` (commented placeholders, no real values):

| Variable | Default | Meaning |
|---|---|---|
| `IMAP_HOST` | none | e.g. `imap.example.com` |
| `IMAP_PORT` | 993 | implicit TLS (IMAP4_SSL) |
| `IMAP_USER` | none | login name |
| `IMAP_PASSWORD` | none (`SecretStr`) | password / app password |
| `IMAP_FOLDER` | `INBOX` | folder to read |
| `IMAP_PROCESSED_FOLDER` | `Verwerkt` | folder where handled mails are moved to (created when missing) |
| `IMAP_POLL_INTERVAL_MINUTES` | 0 | 0 = no background polling; >= 1 = poll every N minutes (values 1..1440; invalid -> startup validation error with a clear message) |
| `IMAP_MAX_MESSAGES_PER_RUN` | 50 | cap per run, the rest is picked up next run |
| `IMAP_TIMEOUT_SECONDS` | 30 | socket timeout |

"Configured" means host, user and password are all set. `Settings.imap_configured` property. The password is a `SecretStr`: never logged, never rendered, never put in exception messages, never in `repr`.

## Acceptance criteria

### Domain: extraction from a mail (pure, no IMAP)
1. `extract_attachments(raw_message: bytes) -> ExtractionResult` parses with stdlib `email` (policy `email.policy.default`) and returns `candidates` (filename, bytes, origin path such as `"bijlage"`, `"doorgestuurd"`) and `skipped` (filename, plain-Dutch reason).
2. A part is a candidate when its bytes sniff as PDF/JPEG/PNG/WebP (`validation.sniff_type`), regardless of the declared content type or file extension (so `application/octet-stream` with a PDF inside works). Parts that do not sniff as such go to `skipped` with reason "Bestandstype wordt niet ondersteund (alleen PDF en foto's)" (HEIC gets its own hint: "Foto's in HEIC-formaat worden niet ondersteund; stuur JPEG of PNG"). Text/html body parts and signatures (`multipart/signed` signature part, `text/*`, `text/calendar`) are ignored silently, not listed as skipped.
3. Nested mails: parts with content type `message/rfc822`, or any attachment whose filename ends in `.eml` and parses as a mail, are parsed recursively with the same rules. Maximum nesting depth 5 and a maximum of 50 candidate parts per mail; beyond that, remaining parts are skipped with a reason. Recursion never reads a mail twice.
4. Small inline images (disposition `inline` or having a `Content-ID`, and smaller than 30 KB) are treated as logos/tracking pixels and ignored silently. An image attachment (disposition `attachment`) of any size is kept.
5. Identical bytes inside one mail (same sha256) appear once in `candidates`.
6. Filenames: decoded RFC 2231/2047 names; when missing, `bijlage.<ext>`. The sanitising is left to `add_document`.
7. Corrupt MIME structure never raises: unparseable nested mails are skipped with a reason; a mail that cannot be parsed at all yields an empty result with a reason.
8. Header helpers: `MailInfo(message_key, from_addr, subject, received_at)`. `message_key` = normalized `Message-ID` header, or `"sha256:" + sha256(raw)` when absent. `received_at` = `Date` header converted to naive UTC, falling back to now. `subject`/`from_addr` are decoded and truncated to 200 chars.

### Domain: running an intake
9. `run_intake(session_factory, storage, mailbox, *, max_messages) -> IntakeReport` processes UNSEEN mails of the configured folder, oldest first, at most `max_messages`. The report has per-run counts: `mails_seen`, `mails_processed`, `documents_new`, `documents_duplicate`, `attachments_skipped`, `mails_without_attachments`, `mails_failed`, plus a list of plain-Dutch `problems`, and `started_at/finished_at`.
10. Per mail, in this order: fetch the raw message with `BODY.PEEK[]` (so nothing is flagged as read yet) -> compute `message_key` -> if an `email_message` row with that key already exists, skip storing (and go straight to step 13, retrying the move) -> extract -> for each candidate `add_document(session, storage, bytes, filename, source="email", source_ref="<van> - <onderwerp>", received_at=mail date)` -> insert an `email_message` row -> `session.commit()` (one transaction per mail, so a failure leaves nothing half-done for that mail).
11. Dedupe, two layers: (a) per mail on `message_key` (same mail fetched again, or the same mail copied into the folder twice); (b) per document on sha256 via `add_document` (same invoice in another mail, forwarded again, or also uploaded by hand). A duplicate never creates a second document, and never changes the status of the existing document (also not when it is already `geboekt`). Counts as `documents_duplicate`.
12. A mail with no usable attachment is still recorded in `email_message` (outcome `geen_bijlage`) and then treated as handled (moved), so the mailbox does not fill up with the same mail on every run; it is counted in `mails_without_attachments` and mentioned in the report ("1 mail zonder PDF of foto is overgeslagen").
13. Marked/moved only after successful storage: only after the commit of step 10 does the mailbox client `mark_processed(uid)`: IMAP `MOVE` to `IMAP_PROCESSED_FOLDER` when the server advertises the `MOVE` capability, otherwise `COPY` + set `\Seen` (no `\Deleted`, no `EXPUNGE`). The processed folder is created when missing (`CREATE`, ignoring "already exists"). If marking/moving fails, the mail is reported as a problem ("Mail is opgeslagen maar kon niet naar de map Verwerkt worden verplaatst"), the documents stay, and the next run does not store anything again (step 10 key check) and just retries the move.
14. If storing fails for a mail (`DocumentStorageFailedError`, database error, any unexpected exception during processing of that mail): rollback, nothing is moved or flagged, the mail stays unread in the folder, the problem is recorded with subject, and processing continues with the next mail (`mails_failed += 1`). One bad mail never blocks the others. A mail larger than 50 MB (`RFC822.SIZE` check before fetching) is not fetched, is left untouched and is reported as a problem.
15. Attachments that fail validation inside a mail that has at least one valid attachment (too large, empty, unsupported) are listed in `problems`/`skipped` but do not fail the mail. If a mail has only invalid attachments and no valid one, it is handled like criterion 12 with the skipped reasons shown.
16. `run_intake` is idempotent: running it twice in a row on the same mailbox yields zero new documents the second time.
17. Documents are never deleted by intake, under any error path. `DocumentStorage.remove` is not called from the new code (a test asserts this by patching `remove` to raise).
18. Single flight: `IntakeRunner` (see approach) ensures only one run at a time within the process. A second request while running returns immediately with `status="bezig"` and does not queue.

### Mailbox client (`imaplib`)
19. `MailboxClient` protocol: `connect()`, `list_unseen()` -> list of `(uid, size)` oldest first, `fetch(uid) -> bytes`, `mark_processed(uid)`, `close()`. `ImapMailbox` implements it with `imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=...)` (certificate verification on), `LOGIN`, `SELECT` (read-write, folder name quoted/encoded properly, modified UTF-7 for non-ASCII), `UID SEARCH UNSEEN`, `UID FETCH (RFC822.SIZE)` and `UID FETCH uid (BODY.PEEK[])`. `close()` always runs (try/finally), also after errors.
20. IMAP failures are mapped to `EmailIntakeError` subclasses with plain-Dutch messages and a stable `code`:
    - not configured (`EMAIL_NOT_CONFIGURED`): "De mailbox is nog niet gekoppeld. Vul IMAP_HOST, IMAP_USER en IMAP_PASSWORD in je .env-bestand in en start het programma opnieuw."
    - login rejected (`EMAIL_LOGIN_FAILED`): "Inloggen bij de mailbox is mislukt. Controleer gebruikersnaam en wachtwoord in je .env-bestand. Gebruikt je mailprovider app-wachtwoorden? Maak er dan een aan."
    - cannot connect / timeout / TLS error (`EMAIL_CONNECT_FAILED`): "Er kon geen verbinding worden gemaakt met <host>. Controleer de servernaam, de poort en je internetverbinding."
    - folder missing (`EMAIL_FOLDER_MISSING`): "De map '<map>' bestaat niet in de mailbox. Controleer IMAP_FOLDER in je .env-bestand."
    - other IMAP error (`EMAIL_IMAP_ERROR`): "De mailserver gaf een onverwachte fout. Probeer het over een paar minuten opnieuw."
    Messages never contain the password; the host and user may appear. Raw exception text goes to the log only (logger `app.email_intake`, password never included; test asserts the password string does not occur in captured logs or in any rendered page).

### Persistence
21. New table `email_message` (migration `0015_email_intake`, model `app/models/email_intake.py`, exported from `app/models/__init__.py`): `id`, `message_key` (unique, not null), `from_addr`, `subject`, `received_at`, `processed_at`, `outcome` (`opgeslagen` | `alleen_dubbel` | `geen_bijlage`), `documents_new`, `documents_duplicate`, `attachments_skipped`, `moved` (bool: false until the mailbox move succeeded). Used for dedupe, move-retry and for showing the last fetches. The migration is reversible and has a migration test in the style of the other migration tests. No data is deleted by the downgrade of unrelated tables.
22. `Document.source_ref` carries "<van> - <onderwerp>" so the inbox detail shows where a document came from. Per document there is no further link to `email_message` (keep schema small).

### Web: Inbox
23. The Inbox page header gets a button "Nu ophalen" (`POST /inbox/ophalen`, htmx-boost off, same-origin protected like other POSTs) next to "Bestand toevoegen" when the mailbox is configured. When not configured, a quiet link "E-mail koppelen" to `/instellingen/email` is shown instead.
24. After the POST the user is redirected (PRG) to `/inbox?melding=opgehaald` and a notice shows the last run result in plain Dutch, for example: "Klaar: 3 nieuwe documenten uit je mailbox gehaald, 1 stond er al." / "Geen nieuwe mail met facturen gevonden." / with problems as a warning list below it ("De mail 'Factuur 123' kon niet worden opgeslagen; hij staat nog in je mailbox en wordt de volgende keer opnieuw geprobeerd."). Configuration/login errors are shown with their message from criterion 20 in an error box and link to the settings page. If a run is already busy: "Er wordt al opgehaald. Wacht even en ververs de pagina."
25. Documents from mail show "E-mail" as source in list and detail (existing), with `source_ref` visible in the detail view ("Ontvangen van ..."). Delete rules for unbooked documents stay as they are; mail-sourced documents are deleted exactly like uploads and are NOT re-created because the mail was already moved and its `message_key` is recorded (a deliberately deleted document does not come back from the same mail). A hint on the settings page says this.
26. The route handlers contain no logic: they call `IntakeRunner.run_now()` and render.

### Web: settings page `/instellingen/email`
27. New entry "E-mail" (term_key `factuurmailbox`) in a new group "Koppelingen" of `SETTINGS_NAV`, page title "Je factuurmailbox". Shows: configured yes/no; host, port, user, folder, processed folder, polling interval ("Automatisch ophalen: elke 15 minuten" or "Uit; gebruik de knop Nu ophalen in de Inbox"); NEVER the password (only "Wachtwoord: ingesteld" / "niet ingesteld"). A numbered plain-Dutch instruction on how to set it up in `.env`, with a copy-able example of the variable names (placeholders only), and the tip to use a dedicated mailbox and to forward bills to it.
28. A button "Verbinding testen" (`POST /instellingen/email/test`) connects, logs in, selects the folder and reports "Verbinding gelukt: er staan N ongelezen mails in <map>." or the plain-Dutch error of criterion 20. It stores and moves nothing.
29. The page lists the last 10 handled mails from `email_message` (date, afzender, onderwerp, result: "3 nieuw", "al aanwezig", "geen bijlage", "nog niet verplaatst") and the result of the last run (in-memory, includes problems).

### Background polling
30. When `IMAP_POLL_INTERVAL_MINUTES >= 1` and the mailbox is configured, the app lifespan starts one asyncio task that waits 10 seconds after start, then runs the intake via `asyncio.to_thread(runner.run_now)` and repeats every N minutes (sleep after completion, so runs never overlap or pile up). It uses the same `IntakeRunner` (and lock) as the manual button. Errors never kill the loop: they are logged and kept as "last result"; after a login failure the loop keeps its interval but logs the problem once per distinct error (no log spam).
31. On shutdown the task is cancelled and awaited cleanly; the lifespan exits without hanging, also when a run is in progress (the thread finishes its current mail; the process does not wait longer than the IMAP timeout). With interval 0 or without configuration no task is created and no network access ever happens (tests rely on this; the default `Settings` in tests never connects).
32. The settings page and Inbox notice tell the user plainly that automatic fetching only works while the program is running.

### Usable without bookkeeping knowledge
33. Terms introduced, each with an entry in `app/domain/glossary.py` (plain Dutch first, explanation max 220 chars, `detect` patterns so `test_plain_language`/info-icon checks apply; use `_NEVER` for terms too generic to force an icon everywhere):
    - `factuurmailbox` - term "Factuurmailbox", plain "Eigen mailadres voor je facturen": "Een apart e-mailadres waar je leveranciers je facturen naartoe laten sturen, of waar je ze zelf naartoe doorstuurt. Het programma haalt de bijlagen eruit en zet ze in je inbox."
    - `imap` - term "IMAP", plain "Koppeling met je mailbox": "IMAP is de standaard manier waarop een programma veilig bij een mailbox kan. Het programma leest alleen mail uit die ene map en verplaatst afgehandelde mail naar de map Verwerkt; er wordt niets verwijderd."
    - `app_wachtwoord` - term "App-wachtwoord", plain "Apart wachtwoord voor een programma": "Veel mailproviders (Gmail, Microsoft, iCloud) eisen een los wachtwoord voor programma's als dit. Dat maak je aan in de beveiligingsinstellingen van je mailaccount."
    The Inbox button "Nu ophalen" has a short helper text/tooltip: "Haalt facturen op uit je factuurmailbox." The `inbox` glossary entry text may be extended with "of per e-mail" if it does not break existing tests.
34. Suggested defaults: port 993, folder INBOX, processed folder "Verwerkt", interval off; the `.env.example` comments explain each in plain Dutch.
35. All user-visible failure texts are the plain-Dutch messages above; no tracebacks, no raw IMAP responses, no error codes without explanation.

## Technical approach

### New package `app/domain/email_intake/`
- `errors.py`: `EmailIntakeError(Exception)` with `code` and Dutch `message` (same shape as `LedgerError`/`DocumentError`; subclass `DocumentError` is NOT used, to keep the document error hierarchy untouched), plus the subclasses of criterion 20.
- `parsing.py`: pure functions `extract_attachments`, `read_mail_info` (criteria 1-8). No IMAP, no DB.
- `mailbox.py`: `MailboxClient` protocol, `ImapMailbox`, `build_mailbox(settings)` (raises `EMAIL_NOT_CONFIGURED`), modified-UTF-7 folder encoding helper.
- `service.py`: `run_intake`, `IntakeReport`, `test_connection`, `recent_messages(session, limit)`.
- `runner.py`: `IntakeRunner(settings, session_factory, mailbox_factory=build_mailbox)` with `threading.Lock` (non-blocking acquire), `run_now() -> IntakeReport | Busy`, `last_report` (thread-safe attribute). Stored on `app.state.email_runner`.
- `__init__.py`: re-exports.
- Sessions: `run_intake` opens its own `Session` from `app.db` sessionmaker per mail (the web request's session is not used, because the run happens in a worker thread for the background task and must commit per mail). The route uses `run_now()` synchronously in a threadpool (`def` route, FastAPI runs it in a thread). SQLite is single-file; the existing `get_session`/engine config is reused (check how `app.db` configures timeouts and set `busy_timeout` if it is not set, so a concurrent web write does not fail the run; if a `database is locked` error occurs for a mail it is handled by criterion 14).
- Charset/encoding robustness: use `email.policy.default`, `part.get_content()` is NOT used for binaries; use `part.get_payload(decode=True)`.

### Config
`app/config.py`: new fields and `imap_configured` property; validator for the interval range. `.env.example`: documented block. Existing `tests/test_config.py` style test added.

### Flow
Manual: Inbox button -> `POST /inbox/ophalen` -> `runner.run_now()` -> store report in `runner.last_report` -> redirect to `/inbox?melding=opgehaald` (or `fout` with the runner's last error) -> inbox renders notice from `request.app.state.email_runner.last_report`.
Background: lifespan task -> same runner.

### Error handling summary
Connection-level errors abort the run (one error shown). Mail-level errors are isolated and recorded in `problems`. Documents and `email_message` rows are written per mail in one transaction; the mailbox is changed only afterwards. Crash between commit and move is healed by the key check.

## Work breakdown (3 parts, disjoint file ownership)

### Part A - Domain, persistence, config (build first; B and C depend on its public API)
Owns:
- `app/domain/email_intake/*` (all files above)
- `app/models/email_intake.py`, `app/models/__init__.py` (one export line)
- `migrations/versions/0015_email_intake.py`
- `app/config.py`, `.env.example`
- `tests/email_intake/*` (parsing, service with a `FakeMailbox`, `ImapMailbox` against a faked `imaplib.IMAP4_SSL`, runner single-flight), `tests/test_config.py` additions, a migration test `tests/test_email_intake_migration.py`.
Public API consumed by others (fix names exactly): `IntakeRunner`, `IntakeReport`, `Busy`/`status` field, `EmailIntakeError` (+`.code`, `.message`), `recent_messages(session, limit)`, `test_connection(settings) -> ConnectionResult(unread_count, folder)`, `Settings.imap_configured`, `Settings.imap_*`.
Tests-first for parsing and dedupe (touch stored documents); use real `email.message.EmailMessage` builders to make fixtures: plain PDF attachment, JPEG, forwarded mail as `message/rfc822`, `.eml` attachment as octet-stream, nested twice, forward with the same PDF twice, inline logo, HEIC, docx, corrupt nested mail, no attachments, Message-ID missing.

### Part B - Web UI (inbox button, settings page, glossary)
Owns:
- `app/web/email_routes.py` (`POST /inbox/ophalen`, `GET /instellingen/email`, `POST /instellingen/email/test`)
- `app/web/routes.py` (one `include_router` line, registered before the placeholder routes)
- `app/web/inbox_routes.py` and `app/web/templates/inbox/list.html` (button, notice, context vars `email_configured`, `email_last_report`)
- `app/web/templates/email/settings.html`, `app/web/templates/inbox/_email_notice.html`
- `app/web/navigation.py` (new "Koppelingen" group in `SETTINGS_NAV`)
- `app/domain/glossary.py` (three terms, extended `inbox` text if wanted)
- `app/web/static/css/inbox.css` (only if styling is needed)
- tests: `tests/test_email_web.py`, plus updates to existing nav/glossary/plain-language tests if they enumerate settings pages or terms.
Depends on Part A's API; may develop against a stub runner placed in `app.state.email_runner` in tests (inject a fake runner with `run_now`/`last_report`) until A is integrated.

### Part C - Background polling in the app lifespan
Owns:
- `app/background.py` (new: `start_email_poller(app) -> asyncio.Task | None`, `stop(task)`, the loop of criteria 30-31, the "log distinct error once" logic)
- `app/main.py` (create `app.state.email_runner = IntakeRunner(...)` always, start/stop poller in `lifespan`)
- `tests/test_email_poller.py` (loop with a fake runner and tiny interval injected, cancellation, no task when interval 0 or unconfigured, error does not kill the loop, `create_app(test_settings)` never connects).
Depends on Part A's `IntakeRunner`; integration point with B is `app.state.email_runner`, which C creates (B reads it).

Integration points: `app.state.email_runner` (created by C in `main.py`, used by B routes); `Settings.imap_*` (A); `IntakeReport` shape (A, rendered by B); `SOURCE_LABELS["email"]` already exists.

## Test strategy
- No real network in any test. `FakeMailbox` implements `MailboxClient` in memory (records `mark_processed` calls, can raise on fetch/mark). `ImapMailbox` is tested against a fake `imaplib.IMAP4_SSL` class returning canned responses (capability with/without MOVE, login failure, missing folder, timeout, socket error), asserting `BODY.PEEK[]` is used, that no `EXPUNGE`/`\Deleted` is ever sent, and that the TLS context verifies certificates.
- Domain tests with real SQLite via existing test fixtures (see `tests/documents/conftest.py`), real `DocumentStorage` in `tmp_path`.
- Key scenarios: idempotent second run; same PDF in two different mails (one document); invoice already booked and mailed again (document status unchanged); store failure on mail 2 of 3 (others handled, mail 2 untouched, retried and succeeds next run); move failure after commit (no duplicate on retry); `remove` never called; password never in logs/pages; max messages cap; Dutch messages exact for the five error classes.
- Web tests with `client` fixture and an injected fake runner: button shown/hidden by configuration, redirect and notice text, busy message, settings page hides the password and shows status, connection test messages, nav entry, glossary entries present and used (info icons) so the existing plain-language tests pass.
- Poller tests with a fake runner and an injected short interval (no real sleeps over 1 s); cancellation test.
- Alembic upgrade/downgrade test for 0015. Full existing suite must stay green.

## Risks and decisions made
- Decision: TLS-only IMAP (port 993, verified certificates). Rationale: credentials in transit; every provider supports it. STARTTLS/plaintext are non-goals.
- Decision: credentials only in `.env`, UI is read-only status. Rationale: instruction "never committed", no secret storage in DB, no password in pages.
- Decision: handled mails are moved to a `Verwerkt` folder (MOVE, else COPY + `\Seen`), never deleted/expunged. Rationale: the user keeps the originals; a unread-only search keeps polling cheap; fits "never delete".
- Decision: dedupe on `message_key` plus document sha256. Rationale: the sha256 is already the canonical document identity; the message key makes retry-after-failed-move safe and stops the mailbox being reprocessed.
- Decision: a user-deleted unbooked document does not return from the same mail (key recorded). A new mail with the same attachment would recreate it; accepted, the user can delete it again.
- Decision: mails without attachments are moved too (recorded `geen_bijlage`). Alternative (leave in inbox) would re-read them each run. The user sees a count so a forgotten body-only invoice is noticeable; the mail remains in `Verwerkt`.
- Decision: small inline images (< 30 KB) are ignored as logos; larger inline images are kept. Risk: a tiny genuine receipt photo flagged inline is dropped; mitigated by listing nothing silently only for `inline`+`Content-ID`+small, everything else is kept or reported.
- Decision: background polling runs only while the app runs; no OS scheduler. Rationale: single-user localhost app, no Docker.
- Risk: SQLite write contention between web requests and a background run. Mitigation: per-mail short transactions, busy timeout, per-mail failure isolation.
- Risk: very large mailboxes on first run. Mitigation: `IMAP_MAX_MESSAGES_PER_RUN` cap, size check before fetch.
- Risk: gmail-style IMAP quirks (labels instead of folders; `MOVE` semantics). The COPY + `\Seen` fallback and created folder cover these; not verified against live servers in tests.
- No business questions outstanding; defaults above were decided by the spec writer.
