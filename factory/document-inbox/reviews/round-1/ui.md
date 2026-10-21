VERDICT: PASS
## Summary
Reviewed by reading templates, CSS and routes (app not run). The inbox list, upload form, result block, status filter, detail and missing-file pages follow the existing design (page-head, table-wrap/data, btn, badge, facts, notice, alert) and reuse existing CSS tokens (--fg, --muted, --surface, --border, --accent, --danger), so light/dark theming works. Form has a proper label for the file input, the result list uses role=status and errors use role=alert, the active filter uses aria-current, the iframe has a title and the image has alt text. Empty, filtered-empty, capped, duplicate, error and missing-file states are all present with the specified Dutch copy. No blocking issues.

## Nice-to-have
- `Content-Security-Policy: sandbox` (required by AC 17) makes Chrome's built-in PDF viewer refuse to render inside the detail-page `<iframe>`; the user may see a blocked/empty frame and need the "Open origineel bestand" link. Worth a manual check in Chrome; if it is blank, consider a note next to the iframe or an `<object>` fallback.
- `--success` is not defined as a token; CSS falls back to a hard-coded #1a7f37 that is not tuned for dark mode.
- `.badge-geboekt`/status colours rely on text plus colour (label is present, so fine); the filter's info icons sit outside the link, which is good for click targets.
- Status filter links have no visible separation from the table on narrow screens beyond wrapping; acceptable.
- Duplicate message uses "geupload" per spec (could be "geüpload").

STATUS: DONE
