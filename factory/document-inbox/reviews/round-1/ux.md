VERDICT: PASS
## Summary
UX lens, round 1. Reviewed spec, diff, templates, routes and glossary, and ran the full suite (657 passed). I did not start the app; the flows were checked through code and the web tests.
- Upload form, helper text, result block (created / duplicate / error with file name prefix), empty states, filter with counts, table columns and detail page all match the spec and are in plain Dutch.
- Errors are domain messages shown verbatim, with no codes visible. A "no file chosen" submit gives a clear message with HTTP 422.
- Glossary: all new terms (status_nieuw, status_herkend, status_geboekt, bewaarplicht, vingerafdruk, extended inbox) exist in `app/domain/glossary.py` and are used via `info()` in the templates. The plain-language tests include the new pages.
- Detail page: file view is inline, there is no delete control, and the explanation of the bewaarplicht is on the page.

## Nice-to-have
- The status badge in the list table and on the detail page has no hover explanation of its own. AC 26 asks for this. The explanation is available through the info icons in the filter row above the table, and on the detail page for all three statuses (the `info()` icon next to the badge). The list-table badge could get a `title=` attribute with the plain phrase.
- The list table has no info icon on the "Status" column header (the spec mentions it). The filter covers it.
- The duplicate message says "geupload" (spec wording), which is a bit awkward. "toegevoegd" would read better.
- The detail page for `herkend`/`geboekt` shows only the info icon after the badge and no visible plain sentence. `nieuw` does show "Nog niet verwerkt."
STATUS: DONE
