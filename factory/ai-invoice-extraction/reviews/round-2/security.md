VERDICT: PASS
## Summary
Round 1 had no blocking findings; delta only (hidden `kind` input and `_review_input` passing it).
- Server-side validation: `review.py:155-158` strips the value and rejects anything outside `KINDS` (invoice, credit_note, receipt, unknown), reports a plain Dutch error and falls back to `invoice`. A tampered hidden value cannot reach the DB unchecked.
- Escaping: value is rendered via Jinja2Templates (autoescape on) from the stored extraction, so no XSS vector. The value is not used in SQL, paths or subprocess args.
- Impact of tampering is limited to the user's own single-user record; no authz change.
## Nice-to-have
- If `invoice_extraction.kind` is NULL (column is nullable), the hidden input renders "None" and the user gets a "geen geldig soort document" error; `{{ extraction.kind or 'invoice' }}` would avoid it.

STATUS: DONE
