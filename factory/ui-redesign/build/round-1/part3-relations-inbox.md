# ui-redesign, Part 3 (Relations + inbox/review): build report

Branch: `worktree-agent-a488fb088ee4f6017` (worktree `.claude/worktrees/agent-a488fb088ee4f6017`).

## Built
- Domain: `list_contacts_page()` + `ContactPage(items,total,page,per_page)` in `app/domain/relations/service.py` (exported from the package). Wraps unchanged `list_contacts`; page < 1 -> 1, beyond last -> last page. Test first in `tests/relations/test_service.py`.
- `/relaties` (`relations_routes.py`, `relations/list.html`, `form.html`, `_error.html`, `css/relations.css`): page_header + CTA, tabs Alle/Klanten/Leveranciers (URL `soort` unchanged, tabs keep `q` and `gearchiveerd`, `info()` for klant/leverancier), toolbar with search and "Toon ook gearchiveerde relaties" as switch (submits on change, plus a visible Zoeken button for no-JS), avatar + name, soort pills, Actief/Gearchiveerd pills, icon actions with aria-label and the existing plain-Dutch `title`, `pager` (50 per page, "Toont X-Y van Z relaties"), empty states incl. "Wis filters". `page` is parsed leniently (garbage -> 1, never 422). Form: three cards (Algemeen, Bedrijfsgegevens, Adres en contact), `.field` + hints, `error_box`, `.form-actions`.
- Inbox (`inbox/list.html`, `_results.html`, `_extract_banner.html`, `_extract_button.html`, `detail.html`, `missing.html`, `css/inbox.css`): header with CTA "Bestand toevoegen" (#upload), upload card with dashed drop-zone (the native file input itself is styled; still exactly one `<input>` in the form), banner and upload/extract results as `notice`/`alert`, tabs Alle/Nieuw/Herkend/Geboekt with count chips and `info()`, status pills, row action "Lees uit" button / "Nakijken" link, cap notice as `notice`, empty states, count line via `pager` (single page; the list is capped, not paged). Detail/missing: breadcrumb, facts card, next-step card, preview card.
- Review (`inbox/review.html`, `_review_line.html`): two columns kept, cards Leverancier / Over de factuur / Wat is er uitgegeven? (flush table) / Totalen, flags as pills (medium warning, low danger, other neutral), "N velden om te controleren" as `notice--warning`, sticky `.form-actions`. Form field names, routes and behavior unchanged.
- `extraction_routes.py`: only renamed the template context var `notice` -> `saved_notice` (it clashed with the imported `notice` macro).

## Tests
`uv run pytest`: 975 passed. New tests in `tests/test_relations_web.py`, `tests/test_inbox_web.py`, `tests/test_extraction_web.py`, `tests/relations/test_service.py` (tabs, pills, pagination/clamping/params, Wis filters, cards, notices, plain-language via `assert_plain_language` for the pages below). One existing assertion changed: `test_filter_counts_and_unknown_value` read "Alle (3)" from visible text; counts are now `tab__count` chips inside the (stripped) tabs nav, so it parses the tab markup instead.
No browser/visual check done.

## Deviations / decisions
1. Inbox pager: the inbox list is capped (500), not paged, so `pager(1, n, n, ...)` only renders the count line "Toont 1-N van N documenten". Real paging would need `app/domain/documents` changes (not mine).
2. Soort pills: "Klant" info, "Leverancier" neutral; both shown for "Beide".
3. Relations form has "Adres en contact" (adres + e-mail/telefoon/notities) instead of a fourth card.
4. Review: button DOM order stays Opslaan then Klaar met nakijken (Enter key still saves without finishing).
5. Context var renames: `notice` -> `flash` (relations list), `notice` -> `saved_notice` (review).

## Notes for the integrator
URLs to add to `tests/test_plain_language.py` PAGES (all pass `assert_plain_language` locally; seed at least one contact / uploaded document first):
- `/relaties`, `/relaties?soort=klant`, `/relaties?q=zzz` (empty filter), `/relaties/nieuw`, `/relaties/{id}/bewerken`
- `/inbox`, `/inbox?status=nieuw`, `/inbox?status=geboekt` (empty filter), `/inbox/{id}`, `/inbox/{id}/nakijken` (without and with an extraction)

Tests counting `aria-current="page"` on /relaties and /inbox now see 2 (sidebar + active tab).
No glossary changes. Screen CSS is loaded via `<link>` in `{% block head %}` and uses tokens only (no hex).

STATUS: DONE
