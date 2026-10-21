VERDICT: PASS
## Summary
Security review of the restyle diff vs main. No exploitable issues found.
- Drawer partial routes (`/inbox/{id}`, `/boeken/{id}`): `is_drawer_request` only checks `HX-Target == "<id>-body"` to pick a partial vs full template. The header is client-controlled but it only changes layout, not authorization or data (same document/entry, same single-user local app). Exact match avoids confusing it with boosted nav. Fine. The storno form posts with `hx-boost="false"`, so error re-render with the full template is not affected.
- Upload modal/dropzone: form still posts to the unchanged `/inbox/upload` with multipart; `accept` is client-side only, as before. Server-side validation was not touched by this diff.
- `/help`: read-only, renders `terms_alphabetical()` from the static glossary; all values auto-escaped.
- localStorage: only `bh.sidebar` ("collapsed"/"expanded"), read in try/catch in `base.html`, compared against a literal string. No sensitive data.
- New JS: no `innerHTML`; dropzone file names are written via `textContent`. Hash-to-dialog selector is sanitised with `replace(/[^#\w-]/g, "")` before `querySelector`, so no selector injection. `data-drawer-open` selectors come from templates only.
- Templates: user-controlled values (`original_filename`, `description`, `reference`, `sha256`) are rendered with default autoescape in text and attribute contexts (`alt`, `title`, `aria-label` are double-quoted). The only `|safe` is `paths[name]` for icons, from a hardcoded dict in `_ui.html`. Preview iframe/img point to the existing `/inbox/{id}/bestand` route; the "open original" link uses `rel="noopener"`.
## Nice-to-have
- `iframe.file-view` for user-uploaded PDFs: consider confirming `/inbox/{id}/bestand` sends `X-Content-Type-Options: nosniff` and a fixed Content-Type (pre-existing route, not changed here).
- `closeDrawer` focus restore and keydown trap are UX details, not security.
STATUS: DONE
