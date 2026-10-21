# Part 1 (Foundation): build report, round 1

Branch: `worktree-agent-af3e1c20540a66ea9` (worktree `<repo>/.claude/worktrees/agent-af3e1c20540a66ea9`)

## Built
- **Tokens** (`app/web/static/app.css`): palette per spec (light + dark), new tokens (`--nav-active-bg/-fg`, `--band-bg`, `--bar-success/-warning`, `--text-3xl`, `--sidebar-width-collapsed`, `--settings-nav-width`, `--drawer-width`), radius 8/12. All old token names kept. No hex outside the token blocks.
- **Full-bleed band without wrappers**: `.content` has no padding; every direct child except `.page-header/.drawer/.drawer-scrim/dialog` gets `margin-inline: var(--edge)` where `--edge = max(32px, (100% - content-max)/2)` (16px on mobile). `.page-header` uses the same `--edge` as padding. Templates need no wrapper. Screen CSS must not set `margin` shorthand on direct children of `.content` (it would reset the inline margin); use `margin-block`.
- **Macros** (`partials/_ui.html`): `page_header(... icon_name, tab_items, tab_label)` (old calls render the same; markup gained a `.page-header__row` wrapper), `stat_cards`, `segmented(items, aria_label, small=False)`, `drawer(id, title, term=None)`, `modal(id, title, open=False, term=None)`, `dropzone`, `pager(..., sticky=False)` (adds `pager--sticky`), icons `help eye sidebar-collapse sidebar-expand download folder calendar`; `settings` icon is now a real gear. Styleguide comment updated.
- **Components in CSS**: stat cards, segmented, drawer + scrim, modal (`dialog.modal`, no-JS fallback `html:not(.js) dialog.modal` = in-page card), dropzone, `.settings-layout/.settings-nav`, `.row--done/.row--warn`, `.pager--sticky`, `.help-fab`, `.empty-note`, reduced-motion, print.
- **Sidebar**: collapse button (`data-sidebar-collapse`, desktop only), collapsed icon-only mode via `html.sidebar-collapsed` (labels/sub-lines kept in the DOM, visually hidden), filled active item, Instellingen as footer row (`nav-group--pinned nav-footer`, gear). Nav link `title` is now `"<label>: <explanation>"` (was only the explanation) so the collapsed state still shows the name. Head script applies `js` and `sidebar-collapsed` (localStorage `bh.sidebar`, try/catch) before paint.
- **JS** (`app.js`, 211 lines): drawer (open via `data-drawer-open`, htmx `afterSwap` open when trigger has `hx-get`, close X/scrim/Escape, focus move/return, Tab trap, closes on `htmx:beforeHistorySave`), modal (`data-modal-open`, `data-modal-close`, backdrop click, `data-open-on-load`, `#hash`, re-init on `htmx:afterSettle`), dropzone drag state + chosen file names, sidebar collapse with aria sync. Existing behaviour untouched.
- **Settings layout**: `SETTINGS_NAV`, `SettingsGroup`, `SettingsItem`, `is_settings_active` in `navigation.py`; template globals `settings_nav`, `is_settings_active`; `base_settings.html`. `is_drawer_request(request, drawer_id)` in `app/web/__init__.py`.
- **/help**: route in `routes.py`, `help.html` (one alphabetical table via new `terms_alphabetical()` in `glossary.py`, client-side search with `data-filter-table`), floating `?` button in `base.html`. 404 and placeholder: icon in band, link to `/help`.

## Tests
`uv run pytest`: 1017 passed (baseline 994). New: `tests/test_help_page.py`, plus additions in `tests/test_ui_components.py` and `tests/test_web.py`. Updated for changed markup: sidebar `title` format (`test_info_component.py`, `test_ui_components.py`), pinned-group class, JS line limit 150 -> 260, token list. `tests/test_plain_language.py` untouched and green (it passes `/help` implicitly because `PAGES` is an explicit list; `/help` is deliberately not in it, noted in a comment in `help.html`).

Contrast (light/dark, computed from the token values): text on `--primary` 5.15 / 8.22; primary on `--primary-soft` 4.56 / 5.69; success/warning/danger on their soft backgrounds 5.75-6.33 / 7.10-8.42; muted on bg 5.81 / 7.96; nav-sub on active item at 90% opacity 4.52 / 7.07.

## Deviations from the spec
1. `--primary-soft`/`--info-soft` light = `#eaf2fb` instead of `#e7f0fa`: the spec value gave 4.47:1 for primary text on it (pills, tab counts), below AA.
2. `nav-sub` on the active item uses 90% opacity, not 85%: 85% gives 4.20:1 in light mode.
3. Added optional params beyond the signatures (backwards compatible): `pager(sticky=)`, `segmented(small=)`, `drawer(term=)`, `modal(term=)`, and block `settings_header` in `base_settings.html` (see below).
4. Sidebar link `title` format changed (see above).
5. No visual browser check was possible here (no headless browser); layout verified by reading CSS and by tests only. Reviewers should run `./boekhouden` and check 375/768/1280, dark mode, collapse, drawer, modal.

## Notes for the integrator and parts 2/3
- **base_settings.html has two blocks**: `settings_header` (full-bleed band, rendered above the columns) and `settings_content` (right column). Part 2 should put `settings_header(current)` inside `{% block settings_header %}`; if it is put inside `settings_content` instead, a CSS fallback renders it as a plain heading (no band).
- Part 2 must change `ledger/_settings_nav.html` so `settings_header` renders only `page_header(current, ... icon_name="settings")` (tabs removed) and make settings templates extend `base_settings.html`. Until then those pages still render with their old tab row and no secondary nav.
- Drawer ids: `boeking-drawer`, `inbox-drawer` (body `<id>-body`). Triggers: `<a href="/boeken/12" data-drawer-open="#boeking-drawer" hx-get="/boeken/12" hx-target="#boeking-drawer-body" hx-push-url="false" hx-boost="false">`. Routes use `web.is_drawer_request(request, "boeking-drawer")`.
- Modal: place `<dialog>` (via `modal()`) as a direct child of the page content so the no-JS fallback gets the page margins. Put `.modal__footer` inside the form inside the modal body (negative margins make it full width).
- `.card--flush` now uses `overflow: clip` (was `hidden`) so a `.pager--sticky` inside it sticks to the viewport.
- The help button sits at `bottom: 5rem` to stay above a sticky pager; it is hidden when a drawer or dialog is open.
- Integrator: no change needed in `tests/test_plain_language.py` for part 1; add part 2/3 URLs as usual.

STATUS: DONE
