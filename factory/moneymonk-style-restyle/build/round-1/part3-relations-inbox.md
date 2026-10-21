# Part 3 (Relations + inbox): build report, round 1

Branch: `worktree-agent-a35f3678058677ed6`

## Built
- Relaties list: band with icon `users`, tabs Alle/Klanten/Leveranciers in the band (`tab_items`), toolbar with search and `segmented` "Actieve relaties | Ook gearchiveerd" (small; keeps `soort`, `q`; resets page; hidden `gearchiveerd=1` kept on search), `info("archiveren")` placed next to the toggle, `pager` sticky. Form: band icon only (cards unchanged).
- Inbox list: band with icon `inbox`, tabs in band, CTA "Bestand toevoegen" (`data-modal-open="#upload"`, href `#upload`). Upload form moved into `modal("upload")` with `dropzone` macro (same action, field `files`, accept, "Toevoegen aan inbox" button, Annuleren). When every upload failed (422/500) the modal re-opens (`data-open-on-load`) with the plain-Dutch error inside; mixed results still show as page notices. Two `stat_cards` pairs ("Te verwerken": Nieuw/Herkend, "Klaar": Geboekt/Totaal) from the existing `counts`. Geboekt rows `row--done`. "Bekijken" button per row opens `inbox-drawer` (htmx `hx-get`, `hx-target="#inbox-drawer-body"`, `hx-boost="false"`). Pager sticky. Empty state no longer has a CTA link (an `href="#upload"` would not open the dialog after load); text points to the header button.
- Detail: new `inbox/_detail_body.html` (facts + file preview; in drawer also filename, open-original, Nakijken, "Open op een eigen pagina"), shared by `detail.html`. `document_detail` returns only the partial when `web.is_drawer_request(request, "inbox-drawer")`. Icons added to band of detail, missing, review. Review totals now `.totals-block` (right-aligned, existing fields/labels only); sticky action bar unchanged.
- CSS: `inbox.css` old file-input dropzone styles removed (macro styles live in app.css), added upload-form, drawer and totals-block rules; no hex, no margin shorthand on content children.

## Tests
`uv run pytest`: 1021 passed. Updated tests for changed markup (empty state text, list layout, relaties tabs/aria-current count 3, soort tab params). New tests: stat cards equal tab counts + `row--done` + sticky pager, drawer trigger/partial/full page/404, upload error re-opens modal with message inside, segmented toggle keeps params. `test_plain_language.py` untouched and green.

## Deviations
- Detail page order: facts, preview, then "Volgende stap" card (was facts, next step, preview) because the shared partial holds facts and preview.
- Drawer content omits the extract button (avoids duplicate `extract-busy-N` ids with list rows); it links to Nakijken / full page.
- No browser check was possible; layout verified by markup and tests only.
- Upload hint text: "Je bestand wordt bewaard en daarna kun je het laten uitlezen." (extraction is manual).

## Notes for the integrator
- `tests/test_plain_language.py` `PAGES`: no new URLs from part 3 (the drawer partial is the same URL `/inbox/{id}`).
- The plain-language key scanner only sees literal `info("key")`, so the `archiveren` info is a separate call next to `segmented`, not a 4th tuple item.
- Modal and drawer markup are direct children of `.content`, as part 1 asked.

STATUS: DONE
