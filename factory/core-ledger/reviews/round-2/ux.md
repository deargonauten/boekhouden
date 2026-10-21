VERDICT: PASS
## Summary
Round-1 blocker resolved. base.html now registers a document-level `htmx:beforeSwap` listener that sets `shouldSwap = true` and `isError = false` for status 409 and 422 only. This is correct htmx 2 usage. The event bubbles, so registering it before the deferred htmx script is fine. Other statuses (2xx, other 4xx, 5xx) keep htmx defaults. `hx-confirm` is handled before the request (htmx:confirm), so the boosted lock/close forms still prompt, and the 409 error pages now swap in like normal boosted responses. Tests: duplicate year POST now asserts `role="alert"` is rendered, plus a presence check for the handler (string-level, weak but adequate).
## Nice-to-have
- The handler test only checks the script text; a browser-level check would be stronger.
- Round-1 nice-to-haves remain open (not blocking).

STATUS: DONE
