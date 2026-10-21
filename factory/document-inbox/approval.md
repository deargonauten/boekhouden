VERDICT: APPROVE

## Reasoning
Second approval, after the human-requested rework of the PDF viewer. The rework commit (3800c41) changes only `document_file` in `app/web/inbox_routes.py`. PDFs are now served without `Content-Security-Policy: sandbox`. Images keep the sandbox. `nosniff` and the inline Content-Disposition stay for all files. The content type comes only from magic-byte detection (PDF/JPEG/PNG/WebP), so the branch cannot be spoofed by filename or client MIME type, and any other value fails closed to the sandbox. Tests cover both branches. The spec (AC 17, D12) was updated to match the code.

Checks run:
- `.venv/bin/pytest -q`: 657 passed.
- Round-2 reviews (code, security) are PASS. ui and ux are n/a for this delta. No REWORK findings.
- Spec and code are consistent.

My earlier concern was that the sandbox CSP would make Chrome refuse to render PDFs, including the fallback link. The cause is removed in code. Browser rendering still cannot be verified by automation. That is a one-minute manual check, not a blocker, because dropping the sandbox is the standard fix and the remaining risk is low.

## Acceptance criteria check
- AC 1-16, 18-25: met, as in the first approval. The rework did not touch them and the tests still pass.
- AC 17 (file route headers): met as amended. PDFs have no CSP, images have `sandbox`, both have `nosniff` and an inline filename.
- AC 26 (badge explanation): partly met, as before. This is a nice-to-have.

## Outstanding issues (none blocking)
- Part C build report (`build/round-1/part-c.md`) is missing. This is a known paperwork gap. The work is in the diff and covered by tests.
- D10 (no delete or hide of uploaded documents) remains an accepted spec decision. A "genegeerd/niet relevant" status is deferred to the extraction/booking feature.
- Security nice-to-have: PDFs now sit on the app origin. This is acceptable for a localhost, single-user app. Revisit it if the app is ever exposed beyond localhost, for example by serving documents from a separate origin.
- Minor items from the first approval, all non-blocking:
  - The list badge has no title.
  - The wording is "geupload".
  - The oversize message always shows 20,0 MB.
  - There is no CSRF/Origin check on the upload.
  - The `--success` CSS token is undefined.
  - Timestamps are naive UTC.

## What the human should look at
Nothing blocks. Open `/inbox/{id}` with a real PDF in Chrome and Safari once to confirm that it renders.

STATUS: DONE
