VERDICT: PASS
## Summary
Round 1 was PASS, so no earlier blocking findings need checking. The delta only drops `Content-Security-Policy: sandbox` for PDFs, in `app/web/inbox_routes.py`. `X-Content-Type-Options: nosniff` and the inline filename-header encoding stay. Images keep the sandbox. The tests now assert both cases.

The served content type can only come from validated sniffing:
- `document.content_type` is set in `app/domain/documents/service.py:76` from `detected.content_type`.
- `detected` comes from `sniff_type`, which returns one of four constants: PDF, JPEG, PNG or WebP. Anything else raises.
- No route or form field writes `content_type`. The client-supplied filename and MIME type are never used for it.
- The route compares against the exact string `application/pdf`. Any other value gets the sandbox. That fails closed.

Risk for a localhost, single-user app:
- Content served as `application/pdf` with `nosniff` is handled by the browser's PDF viewer, not rendered as HTML in the app origin. PDF JavaScript runs in the viewer's own sandbox.
- A polyglot (HTML containing `%PDF-` in the first 1 KB) is still served as `application/pdf` and not sniffed to HTML, because `nosniff` is set.
- The residual risk is a browser PDF-viewer vulnerability, which a malicious invoice from email intake could target. That is the same exposure as opening the PDF from disk, and it is acceptable here. The spec documents it in AC 17 and D12.

## Nice-to-have
- Unsandboxed PDFs sit on the app's origin, so a browser PDF-viewer bug would have a slightly larger blast radius than before. If the app ever stops being localhost-only, revisit this, for example by serving documents from a separate origin.
- `sniff_type` accepts `%PDF-` anywhere in the first 1024 bytes. That is lenient but harmless given `nosniff`.

STATUS: DONE
