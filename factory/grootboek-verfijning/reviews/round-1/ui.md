VERDICT: PASS
## Summary
Read the diff of templates, CSS and JS. The new btw-codes page, Grootboek columns/modal and the inbox/manual-boeking changes reuse existing components (settings_header, modal, pill, btn-icon, btn-small, field__hint, table-wrap, row-actions). All referenced CSS classes and icons exist. Labels are associated with inputs, fieldset/legend is used for the checkbox group, icon buttons have aria-labels, and rubriek fields have hints via aria-describedby. Lock states on system accounts are explained with a title. Wide tables scroll inside .table-wrap.

## Nice-to-have
- Grootboek table now has 7 columns with inline forms per row; on narrow screens it relies on horizontal scroll. Acceptable for a settings page.
- Lock explanation on system accounts is only a `title` tooltip (not reachable by keyboard/touch); a visible muted text would be better.
- btw-codes icon buttons use the same aria-label for every row ("Btw-code bewerken"); including the code name would help screen-reader users.
- Per-row "Opslaan" buttons in Grootboek could be replaced by auto-submit later.

STATUS: DONE
