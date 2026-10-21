VERDICT: PASS
## Summary
Round-1 blocking finding is resolved. `review.html` now carries the extraction kind in a hidden `kind` input, and `_review_input` (extraction_routes.py:405) passes it to `ReviewInput`, falling back to "invoice" only when the field is missing. The new test `test_review_keeps_document_kind` covers both "opslaan" and "klaar". It checks that the hidden input is rendered and that `credit_note` is still stored after the POST. tests/test_extraction_web.py passes (25 tests). The delta is small (4 files) and adds no new problems.

## Nice-to-have
- Round-1 nice-to-haves still stand (`_extract_one` does not store the model on a failed row, and the CLI error regexes are broad). Neither blocks.

STATUS: DONE
