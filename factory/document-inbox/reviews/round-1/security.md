VERDICT: PASS
## Summary
Security lens reviewed storage, validation, service, routes and templates. No real vulnerabilities found.
- Path safety: stored path is built only from the computed sha256 and an ext from a fixed map; the user filename is only sanitized metadata (basename, control chars stripped, 255 max). No traversal.
- Type detection is by magic bytes; stored content_type is the detected one. Served with nosniff and CSP sandbox, inline name RFC 5987-quoted. SVG/HTML cannot be stored.
- Storage: atomic temp + fsync + link (never overwrites), 0o444, existing file verified by hash, no delete/truncate path (temp cleanup only unlinks its own temp file).
- SQL via ORM only; templates rely on Jinja autoescape for filenames (no |safe). Error messages do not leak exception text; storage errors logged/wrapped.
- Upload size: chunked read capped at limit+1 and domain re-checks.
- No secrets or sensitive data logged.

## Nice-to-have
- `await request.form()` makes Starlette spool every file to a temp file before `_read_limited` runs, so the 20 MB cap bounds memory but not temp disk use. Harmless for a localhost single-user app.
- No CSRF/Host-header check on `POST /inbox/upload`: any web page the user visits could post a file to localhost. Low impact (add-only, no delete, hash-deduped), consistent with the "no authentication" non-goal; consider a global Origin check later.
- Chrome may refuse to render PDFs inside an `<iframe>` when the response carries `Content-Security-Policy: sandbox` (spec-mandated, D12). Worth a manual check; the "Open origineel bestand" link is the fallback.
- PDF sniffing accepts `%PDF-` anywhere in the first 1024 bytes (as specified); polyglots are neutralised by the sandbox header.

STATUS: DONE
