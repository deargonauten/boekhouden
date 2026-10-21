VERDICT: PASS
## Summary
Read-only review of the company form template, routes, nav and settings header. The screen reuses the existing patterns: `base_settings.html`, `settings_header`, `card`/`form-grid`/`field`, `relations.css`, and the `notice` and `error_box` macros. Labels are tied to inputs with `for`/`id`. Hints are linked with `aria-describedby`. The required marker matches the relations form. The error box has `role="alert"` and the notice has `role="status"`. The grid collapses to one column on narrow screens via the relations.css media query. The completeness notice is a warning, not an error. Typed values are kept on 422. The nav group and breadcrumb are as specified. The renamed relations card heading and the new `titles`/`terms` entries are consistent. I did not run the app visually. This review is based on the code and CSS.
## Nice-to-have
- The `country`, `postal_code` and `city` fields have no hints. `country` is a bare 2-letter input; a short hint ("NL voor Nederland") would help.
- `postal_code` and `city` sit in the same row as `country` in a 2-column grid, so `country` ends up alone on its own row. A `form-grid--3` row (a class that exists in inbox.css) would look tidier.
- The completeness notice shows both on 422 and on success. That is fine, but the flash and the "compleet" notice stack as two green boxes after saving.

STATUS: DONE
