VERDICT: REWORK
## Summary
The setup flow uses clear Dutch, central glossary explanations, suggested defaults, and existing UI components. One integration defect hides mailbox failures and prevents users from knowing how to recover.

Reviewed `main...HEAD`; accepted the reported 2617 passing tests without rerunning the suite. Visual browser verification was unavailable: no app responded on localhost:8000.

## Blocking findings
- [high] app/web/templates/inbox/_email_notice.html:6 and app/web/email_routes.py:74: The real runner returns an `IntakeReport(status="fout", error_message=...)` for login, connection, and folder failures; it does not raise them. The route redirects to the normal result, and the shared template ignores the error fields, displaying “Geen nieuwe mail met facturen gevonden.” This also hides background failures on the settings page. Users can believe fetching succeeded while invoices remain uncollected. → Render failed reports as an error box containing the Dutch recovery message and a settings link, on both pages, without the empty-mailbox notice. Verify with a returned failed report; the current web test only covers a fake runner that raises.

## Nice-to-have
None.

STATUS: DONE