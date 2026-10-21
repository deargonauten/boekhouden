VERDICT: PASS
## Summary
Templates and CSS were reviewed by reading them; the app was not run. They meet the spec's layout criteria (AC 6-9). The sidebar is fixed at 220px on wide screens, with a dark sidebar and light content. Instellingen is pinned to the bottom with margin-top:auto. Below 768px the sidebar is hidden behind a CSS-only checkbox toggle. Dark mode is handled with prefers-color-scheme variables. Contrast looks fine: sidebar text #cbd5e1 on #1f2937, white on the #2f6fed active item, and muted text #5d6879 on #f6f7f9 all clear 4.5:1. Both `aria-current` and the `active` class are set, `lang="nl"` is present, and the nav has an aria-label. No CDN is used. hx-boost swaps the body, so the toggle resets to closed after navigating on mobile, which is the right behaviour.

## Nice-to-have
- base.html:11-12: the toggle checkbox has `tabindex="-1"` and `aria-hidden`, and the label is not focusable. Keyboard and screen-reader users on a narrow viewport cannot open the menu. Make the label a `<button>` or a focusable label, or use a small JS toggle with `aria-expanded`.
- app.css (mobile): the off-canvas sidebar is only moved with transform, so its links stay in the tab order while invisible. Add `visibility:hidden` while closed.
- app.css: there are no custom `:focus-visible` styles. The browser default outline is acceptable, but an explicit light outline on `.nav-link` would be more reliable against the dark sidebar.
- app.css: the open mobile menu has no backdrop, and `top: 2.9rem` is hard-coded against a toggle bar that is about 3rem high. Both are cosmetic.
- app.css: dark mode only overrides --bg, --fg, --muted and --sidebar-bg. In dark mode the sidebar (#0b0e13) is darker than the page, which is fine, but `.sidebar-header` hard-codes #fff instead of a variable.

STATUS: DONE
