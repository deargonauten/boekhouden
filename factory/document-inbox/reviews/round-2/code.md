VERDICT: PASS
## Summary
Delta reviewed (HEAD~3, app/tests/spec). `document_file` in app/web/inbox_routes.py now builds headers once and adds `Content-Security-Policy: sandbox` only when `content_type != "application/pdf"`; Content-Disposition and nosniff are kept for all files. Content type comes from magic-byte detection, so the branch cannot be spoofed by filename. Tests: the PDF test asserts no CSP header; the image test asserts png type, nosniff and CSP sandbox, so both branches are covered. Spec AC 17, the web-test line and D12 match the code and give the rationale. `.venv/bin/pytest -q`: 657 passed. No round-1 blocking findings existed.

## Nice-to-have
- A defense-in-depth CSP for PDFs (e.g. `default-src 'none'; object-src 'self'`) was consciously skipped (D12); fine for a localhost single-user app.

STATUS: DONE
