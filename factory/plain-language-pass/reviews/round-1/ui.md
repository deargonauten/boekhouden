VERDICT: PASS
## Summary
Reviewed by reading CSS/templates (no server run). Tooltip works on hover and keyboard focus (`:hover` and `:focus-within`, button is a real focusable control with aria-label and aria-describedby, role=tooltip). Dark mode is covered through `--surface`, `--border`, `--fg`, which have dark overrides. At 360px the tip is capped at `min(20rem, 90vw)` and anchored to `.content` with left:1rem, so it does not clip. The `.table-wrap` overflow does not clip it, because its containing block (`.content`) sits outside the wrap. Sidebar sub-lines: `#a9b4c4` on `#1f2937` and `#0b0e13` has enough contrast; the active entry uses white on the accent; the hover and active backgrounds were moved to `.nav-entry` so the entry highlights as one block. The `title` tooltips on the sidebar and subnav add a mouse-only hint and nothing depends on them.
## Nice-to-have
- The tip is positioned against `.content` (left:0), not the icon. Tips for icons far to the right appear at the left edge, away from the icon. Because they are detached, the pointer cannot move onto the tip without it closing. Wrapping `.info` in `position: relative` with a clamped offset would fix both.
- No Escape-to-dismiss (WCAG 1.4.13); the tip stays up while the button has focus.
- The info button is about 18px, a small touch target. On touch the tip only shows after tapping and holding focus, and there is no explicit tap-away behaviour.
- The sidebar link `title` carries the full explanation. It is invisible on touch and repeats the sub-line for screen readers. The `.nav-sub` text is not tied to the link with aria-describedby.
- The tip's `box-shadow` on dark surfaces is nearly invisible, but the border carries it.
- The `.nav-pinned` margin rules still apply only in the non-term branch (Instellingen). That is correct today, but a future pinned item with a term_key would lose the pinning.
STATUS: DONE
