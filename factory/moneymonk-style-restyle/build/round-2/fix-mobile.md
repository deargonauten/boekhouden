# Round 2: fix-mobile

Branch: worktree-agent-a9e1e09acf088820a

## Fixes
1. Search box height: in the `max-width: 899px` toolbar rule, `.toolbar__search { max-width: none; flex: 0 0 auto; }`. Measured search height at 375px: 41px (was about 255px).
2. Horizontal page scroll at 375px (app.css, mobile block): `.content { overflow-x: clip; }` and `.card--flush { contain: paint; }`.
   Root causes found by injecting CSS candidates in a real 375px viewport:
   - /boeken and /instellingen/grootboek|dagboeken: the `.table-wrap` inside `.card--flush` (overflow: clip) leaked its scroll width to the page. `contain: paint` on the card fixes it (min-width / width tweaks did not).
   - /boeken/nieuw and /instellingen/boekjaren: hidden absolute `.info-tip` bubbles outside any scroller (form fields, settings-nav items) extended the page. `overflow-x: clip` on `.content` fixes it.
3. Boeking "Regels" table (drawer and detail page): class `lines-detail`; `#` and `Toelichting` columns hidden in the drawer and at <=899px, header labels wrap, amounts nowrap. Both Debet and Credit amounts are now visible at 375px; Btw-tarief scrolls inside the wrapper (checked by screenshot).

## Verification (Playwright/Chromium, real 375px viewport, scratch DB with 8 boekingen, data/boekhouden.db untouched)
documentElement.scrollWidth, before -> after (clientWidth 375):
- /boeken 650 -> 375
- /boeken/nieuw 446 -> 375
- /instellingen/grootboek 511 -> 375
- /instellingen/dagboeken 497 -> 375
- /instellingen/boekjaren 502 -> 375
- /inbox 375 -> 375
- /relaties 375 -> 375
- /boeken/1 (detail) -> 375

The Chrome extension was disconnected, so Playwright (homebrew python) was used instead; the viewport is real 375px, no iframes.

## Tests
- Added tests/test_mobile_css.py (CSS assertions for the rules above).
- Full suite: 1030 passed, 1 deselected.

## Notes for integrator
- Rules are scoped to the mobile media query (desktop unchanged), except the Regels header wrap and amount nowrap, which apply everywhere.
- Not tested in real drawer-open state at 375px other than the detail page render; same partial is used.
