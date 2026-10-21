VERDICT: HUMAN_REVIEW

## Reasoning
Process and code are in good shape. The spec was approved, three parts were built and integrated, and review round 1 ran. All four reviewers (code, security, ui, ux) returned PASS with only nice-to-haves. I ran `uv run pytest` on the branch: 994 passed, 1 deselected. That includes test_plain_language, test_info_component and test_web. A grep found no hex colors in the screen CSS and no external http(s) src/href in the templates. app.js is 98 lines (limit 150).

This is a visual redesign, and nobody has looked at the main visual paths. The ui reviewer only saw /relaties in dark mode, empty. Light mode is the default theme. Mobile width (375/768, criterion 11), populated tables, and the JS-driven pieces (drawer, tooltip placement, kebab menu, boosted-navigation CSS loader) were verified by CSS and markup reading only. The build reports also say no builder did a browser check. The spec itself says the manual visual check at 375/768/1280 is a reviewer task, and it was not done. Contrast was only computed by script. Whether it "looks nicer" ("mooier") is the user's own product judgement. For those reasons I do not want to auto-approve.

## Acceptance criteria check
1. Tokens, no hex outside :root: met (grep clean, tested). Light and dark readability: dark seen, light not seen.
2. New sidebar and page_header with breadcrumb on all pages: met by tests and markup.
3. Macros in _ui.html with tests: met (tests/test_ui_components.py, 250 lines).
4. Card, table and pills on list pages; pager on boeken, relaties, inbox: met. Inbox only shows the count line, because the list is capped and not paged. That is acceptable.
5. /boeken ?q with dagboek and page, clamping: mostly met. 0, negative and too-large values are handled. A non-numeric `?page=abc` returns 422 instead of falling back to 1. This is minor.
6. /relaties page, 50 per page, "Toont X-Y van Z": met.
7. Inbox status tabs with counts and a notice for the cap: met.
8. .field forms, error_box and notice: met.
9. Plain-Dutch empty states: met per the ux review.
10. Focus rings, aria-labels, Escape on tooltips: met in CSS and JS by reading. Not exercised in a browser.
11. Responsive at 375/768/1280 with no horizontal scroll: not verified.
12. No external requests: met.
13. All tests pass: met.
14. Plain-language and glossary coverage: met. Tests pass and PAGES was extended.
15. Icon actions with aria-label and plain-Dutch title: met.

## Outstanding issues
None blocking. All of these are nice-to-have and non-blocking:
- `/boeken?page=abc` gives 422. Use `page: str` with lenient parsing, as /relaties does.
- `page.strip().isdigit()` in relations_routes accepts characters like "²", and `int()` then raises a 500. Use try/except.
- fiscal_years heading "Boekjaren (Boekjaar)" is redundant. Periods show numbers, not month names. All 12 lock buttons share the same aria-label.
- Empty KvK/BTW/IBAN cells are blank. Dagboek tabs show a code prefix ("VK Verkoopboek").
- Without JS on small screens, the sidebar stacks above the content.
- No `--danger-fg` token.
- Inbox review still uses some legacy `.review-*` styling.

## What the human should look at
Run `./boekhouden` and click through, in light mode first (then dark), at about 1280px and 375px:
- /relaties and /boeken with a few rows, and with more than 50 for the pager.
- /inbox, plus a review page (/inbox/{id}/nakijken).
- /boeken/nieuw, and /instellingen/grootboek, /dagboeken and /boekjaren.
Check:
- the mobile drawer opens and closes,
- tooltips are not clipped inside table headers,
- the row menus and icon buttons are usable,
- tables scroll inside their card and the page does not scroll sideways,
- the overall look matches the intended calm indigo direction.
If it looks fine, merge. The nice-to-haves can follow as a small cleanup.

STATUS: DONE
