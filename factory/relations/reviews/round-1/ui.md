VERDICT: PASS
## Summary
The relations list and form reuse the existing design vocabulary (page-head, table-wrap, data, btn, btn-secondary, fields, hint, alert, badge-muted, inactive). The few new CSS rules are small and use existing tokens. The list has an empty state, a "no results" state, a muted "Gearchiveerd" badge and a status notice. The form re-renders with an error alert (role=alert), keeps the entered values, and ties hints to inputs via aria-describedby. Inputs have wrapping labels, and fieldset/legend is used for the role group. Info icons come from the shared macros. Nothing blocks.

## Nice-to-have
- form.html: the three hint paragraphs sit below the whole KvK/BTW/IBAN row instead of under each field. On narrow widths the hints can end up far from their input. Per-field wrapping would read better.
- form.html: errors are only listed in the top alert. Invalid fields get no aria-invalid and no highlight.
- list.html: the archive/restore button is a full btn-secondary on every row, which is visually heavy in a long list. A link-style button would be quieter.
- app.css: `.empty` and `.stack` classes are used but not defined. They are harmless, but either style them or drop them.
- list.html: the Notities field is a single-line input. A textarea would suit longer notes.

STATUS: DONE
