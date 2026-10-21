VERDICT: APPROVE
## Reasoning
Process was followed. The spec was approved, parts A, B and C were built, and integration was done. Review round 1 had one blocking code finding: the review form reset the document kind (for example a creditnota) to `invoice` on save. Round 2 fixed it with a hidden `kind` input, server-side validation of the value, and a test (`test_review_keeps_document_kind`) written first. All four round-2 reviews (code, security, ui, ux) are PASS. The full suite passes with `uv run pytest -q` (924 passed). The Claude CLI extractor spot-check matches the safety criteria: argument list, `--tools Read`, `--allowedTools Read`, `--add-dir`, `--no-session-persistence`, temp dir cleaned up in `finally`. The glossary has the new keys (`uitlezen`, `nakijken`, `creditnota`), and `anthropic` was added to the dependencies. The deliberate replacement of a literal OAuth flow with the user's own `claude -p` login plus an `ANTHROPIC_API_KEY` fallback was approved by the user before the build, so I do not count it as a deviation.
## Acceptance criteria check
- Extractor interface, fake, factory, CLI and API backends, error types (AC 1-6): met (by code spot-check and tests)
- Validation, storage, status transition, and the review, save and batch routes (AC 7-25): met (tests pass; reviewed in rounds 1 and 2)
- Money as integer cents, shown with the `euro` filter (AC 26): met
- Plain-Dutch labels, glossary entries, defaults, and error messages (AC 27-30): met (ux review PASS)
- `test_plain_language` PAGES extended (AC 31): met
- Safety and logging (AC 32-33): met (security review PASS)
## Outstanding issues
Non-blocking nice-to-haves only:
- If `invoice_extraction.kind` is NULL, the hidden input renders "None" and the user sees an error. `{{ extraction.kind or 'invoice' }}` would avoid it.
- `_extract_one` does not store the model on a failed row.
- The CLI error-mapping regexes are broad.
- `.check-summary.has-flags` uses an undefined `--warn-fg` variable with a light-theme fallback, which gives lower contrast in dark mode.
## What the human should look at
Nothing is required. Optionally, try one real extraction with your own `claude` login to judge extraction quality and speed.

STATUS: DONE
