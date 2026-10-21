VERDICT: PASS
## Summary
Reviewed review.html, _review_line.html, _extract_banner.html, _extract_button.html, the inbox list/detail changes and the app.css additions (read from code; app not run).

The screen follows spec item 22. It has two columns on desktop with a sticky PDF/image viewer on the left. Below 900px it stacks and the viewer drops to 50vh. It reuses existing classes (.fields, .alert, .notice, .hint, .btn-secondary, .table-wrap, .page-head) and existing CSS tokens (--surface, --border, --accent, --danger). Dark-mode overrides exist for the flag badges.

States are covered:
- no extraction yet
- failed extraction, with a retry button
- busy indicator, with the button disabled via hx-disabled-elt
- backend-not-logged-in banner
- validation errors in role=alert
- save notice in role=status

Accessibility is mostly sound:
- Line inputs have aria-labels.
- The iframe has a title and the image has alt text.
- The delete column has a visually-hidden header.
- Flags use text labels as well as colour.
- Inputs sit inside labels.

## Nice-to-have
- Flag messages are not linked to their inputs with aria-describedby. Screen-reader users hear the reason only as nearby text.
- The line-items table is 6 columns with min-width 7rem inputs inside a half-width column. It will scroll horizontally between 900px and about 1200px. The table-wrap handles this, but a narrower layout or a stacked line card would read better.
- `.check-summary.has-flags` uses an undefined `--warn-fg` with a light-theme fallback (#8a5a00). In dark mode that colour has lower contrast. The flag-medium colours are hardcoded too. Define the token in :root and the dark block.
- The "Verwijder regel" button uses an inline onclick, with no confirmation and no focus management after removal.
- The "Regel toevoegen" row has no way to be undone. This is minor.
- The visually-hidden class is new here. If a similar helper exists or is added elsewhere, consolidate.
- The inbox list banner is shown even when there are no documents to read out.

STATUS: DONE
