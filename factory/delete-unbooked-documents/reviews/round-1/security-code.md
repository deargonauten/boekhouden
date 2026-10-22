VERDICT: REWORK
## Summary
Domain checks protect booked documents, file removal validates sha/ext, and bank storage refuses deletion. Extraction deletion handling and unlink-error rollback are covered. Used the supplied test result: 1707 passed, 1 deselected.

## Blocking findings
- [high] app/web/inbox_routes.py:239: The irreversible deletion POST accepts requests without a CSRF token or origin validation; no application middleware supplies protection. An external page can submit a form to `http://127.0.0.1:8000/inbox/1/verwijderen`, bypassing the confirmation page and deleting an unbooked document wherever browser localhost access is permitted. Sequential IDs make targets predictable, and CORS does not prevent form submissions. → Require a validated CSRF token or equivalent same-origin protection before deletion. Add targeted tests proving foreign-origin requests cannot change rows or files and the legitimate confirmation flow still succeeds.

## Nice-to-have
- tests/documents/test_delete.py:test_service_never_commits: The rollback test verifies restored rows but omits that the file remains deleted. Document and assert this transaction limitation explicitly so callers understand that rolling back after a successful deletion cannot restore the original file.

STATUS: DONE