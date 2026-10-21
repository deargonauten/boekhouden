VERDICT: REWORK

## Summary
First real visual check. App run on a scratch SQLite DB (8 boekingen, 3 relaties, 3 inbox PDFs), real Chrome screenshots. Desktop (about 1400px viewport; window resize does not change the viewport in this Chrome setup) looks good and clearly follows the MoneyMonk references. Mobile (375px) has two clear layout bugs.

Verified visually:
- Desktop dark (system default): Boeken list, booking drawer (open, scrim, help FAB hidden), Inbox with stat cards, add-file modal (dropzone, footer), Relaties list, Nieuwe boeking form (sticky save bar), Boekjaren (stat card, settings nav), Grootboek with sidebar collapsed (icon-only, settings gear active, settings nav column, header band).
- Desktop light (dark media rules disabled via injected CSS): Boeken list. Full-bleed white band, big icon + title, tabs with underline, gray body, white bordered card, sticky "Toont 1-8 van 8" pager, filled blue active nav item, round help button. All as intended.
- 375px: emulated by loading Boeken, Inbox, Grootboek in 375px-wide iframes (media queries respond to iframe width). Hamburger top bar, stacked stat cards, tabs scrolling horizontally, tables scrolling inside their card.
- Not verified: 375px drawer/modal/sidebar drawer open, mobile light mode, dark+light of every page, print, keyboard focus rings, contrast numerically, tooltip clipping on hover (no clipping seen in static states), Dagboeken/Help/placeholder/404 pages.

## Blocking findings
- [high] app/web/static/app.css:487-489 (`.toolbar` column on mobile + `.toolbar__search { flex: 1 1 16rem }` at line 481): at <=~700px the toolbar is `flex-direction: column`, so the 16rem flex-basis becomes HEIGHT. The search field renders about 255px tall (toolbar 281px) on Boeken and Grootboek and pushes the table out of view. → in the mobile rule set `.toolbar__search { flex: 0 0 auto; }` (or `flex-basis: auto`); search box should be one input high.
- [high] Mobile page-level horizontal scroll: at 375px `documentElement.scrollWidth` is 637 on Boeken and 511 on Grootboek (window.scrollX reached 262 and 136); Inbox is fine (375). The whole page including header band and sidebar top bar slides sideways, which breaks the "mobile: no horizontal page scroll" intent of the spec. Visible text/elements are clipped inside scroll containers (tabs, tables) as designed, so the overflow comes from something else, most likely absolutely positioned hidden tooltip bubbles (`.info-tip`, e.g. in `.settings-nav` and tab bar, right edge up to 560px) escaping the nearest scroller. → ensure nothing contributes to document overflow at 375px (e.g. `overflow-x: clip` on `.content`, or position/clamp tooltips); verify `scrollWidth == clientWidth` on every page.

## Nice-to-have
- Booking drawer, "Regels" table: table is 979px wide in a 437px wrap, so the Credit and Btw-tarief columns are hidden behind a horizontal scroll; the credit amount of a booking is invisible without scrolling. Consider a compact layout in the drawer (hide Btw/Toelichting, or stack).
- Data tables: `th` background stops before the last (action) column, leaving an un-shaded gap at top right (Boeken, Grootboek). Give the empty action `th` the same background.
- Help FAB overlaps the right edge of table/form content (Nieuwe boeking Toelichting field, bottom-right rows). Consider bottom padding on `.content` or moving above the sticky save bar.
- Drawer header: the info icon sits far from the "Boeking" title (flush to the right area).
- Dark mode band (`--band-bg` = surface) is barely distinct from the body background; only the bottom border separates them. Acceptable.

STATUS: DONE
