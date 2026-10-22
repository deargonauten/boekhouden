VERDICT: PASS
## Summary
Reviewed security, code and UX/UI in one pass against spec section 4.

- Security: no problems. The new routes only take an int id (`{document_id:int}`, `boeking: int`) plus `q`/`tab`/`page`. Jinja autoescape is on and there is no `|safe`. Search uses ORM `ilike` with `%`, `_` and `\` escaped. Unknown tabs fall back to the default, and page numbers are clamped. Errors render only the Dutch `message`, never codes or tracebacks.
- Migration 0008: the trigger only passes an UPDATE when `OLD.source_type IS NULL AND OLD.source_id IS NULL`, both new values are non-null, and every other column is unchanged. So the source link can be filled exactly once and nothing else can change. The downgrade restores the strict trigger, and `test_source_link_can_be_set_once` and `test_downgrade_restores_strict_trigger` cover both. I read the SQL and the tests but did not run them: `python -m pytest` failed as "command not found", and I did not retry.
- Booking: `book_extraction` does the entry, invoice, source link, document status and learned defaults in one `begin_nested` savepoint. An `IntegrityError` becomes "al geboekt", and an already booked document is refused up front. Entries are built from integer cents, use the printed VAT, and balance by construction. Credit notes swap the sides. Logic stays in `app/domain/purchase`, and the handlers are thin (the GET preview is read-only).
- UX: the preview leads with plain Dutch (summary sentence, "Zo wordt het geboekt", "Nog te betalen"). Every new term has a glossary entry and an info icon. Errors say what to do and link to the review field. There is an "Eerst nakijken" state, and the `/inkoop` empty states are clear.

## Nice-to-have
- `app/web/templates/purchase/list.html` (open tab): the supplier link searches by name text, so a name that is a substring of another supplier's also shows that one's invoices. Linking by `contact_id` would be exact.
- `app/domain/purchase/service.py`: `preview` and `book` call the ledger's private helpers (`_find_period`, `_check_accounts`, `_check_vat_codes`). Exposing them publicly would be more robust.
- `app/web/booking_routes.py`: the template helpers each open their own short DB session per render. This is fine for a single user, but the data could be passed in from the handlers instead.
- `app/web/booking_routes.py`: the success redirect carries `boeking=<entry id>` straight to `/boeken/{id}`. It is harmless, since it is an int that only forms a link.
- The "unique partial index" duplicate guard in AC7 became a service pre-check (Builder A's reasoned deviation 2). The `UNIQUE(document_id)` constraint covers double-submit of the same file. Two different documents with the same supplier and number submitted in a race could both get through, which is negligible for a single-user local app.

STATUS: DONE
