VERDICT: REWORK
## Summary
The feature is well structured and matches the spec closely. All 922 tests pass. Routes are thin, the extractor runs between two commits, the CLI call uses an argument list with `ANTHROPIC_API_KEY` removed, the integrator's `account_code` and `BackendStatus.kind` changes are consistent, and there are no float-to-cents paths. I found one real bug: the review form drops the document `kind`, so saving a review silently changes a credit note into an invoice.

## Blocking findings
- [medium] app/web/extraction_routes.py:62-67 and :391-405 (`HEADER_FIELDS`, `_review_input`), app/web/templates/inbox/review.html: the review form has no `kind` field and `_review_input` never sets it. `ReviewInput.kind` therefore always defaults to `"invoice"`. Every "Opslaan" or "Klaar met nakijken" overwrites `extraction.kind` (service.py:397) with `invoice`. A `credit_note`, `receipt` or `unknown` from the model is lost on the first save. The creditnota notice (review.html:52) and info flag (AC 10j) vanish, and the booking feature, which needs the sign, would see "invoice". Done looks like:
  - The existing kind is carried through the form, either as a hidden input or as a select "Soort document" (factuur / creditnota / bon) with `FIELD_LABELS["kind"]` already present, and `_review_input` passes it to `ReviewInput`.
  - A web test checks that a credit_note extraction stays `credit_note` after save and finish.

## Nice-to-have
- `_extract_one` calls `store_failure(session, id, extractor.name, exc)` without `extractor.model`, so the failed row has `model=NULL`. `run_extraction` passes it.
- `store_failure` returns early when a previous `ok` extraction exists, which is sensible. The route still shows the error on the detail page, but the document's review page keeps showing the old result with no hint that the retry failed.
- `_NOT_LOGGED_IN` in `claude_cli.py` matches the bare word "authentication" and `\b401\b`, and `_RATE_LIMIT` matches `\b429\b` in free text. A model result mentioning those could be misclassified. This is low risk because it only applies when `is_error` is true.
- `cli_status` runs `claude auth status` synchronously, with a 15 s timeout, on every page render that shows the banner once the 60 s cache expires. This is acceptable for a single-user app.
- The `extract_all` result text is built from `error.message`. This is fine, but the plain Dutch "N nog te gaan" wording is only visible if the template renders `extract_left`. I did not verify the wording.

STATUS: DONE
