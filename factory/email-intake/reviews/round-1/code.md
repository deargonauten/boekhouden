VERDICT: REWORK

## Summary

The intake transaction and deduplication flow look sound. One integration bug hides connection failures from users. Reviewed against the spec and supplied result of 2617 passing tests; the full suite was not rerun.

## Blocking findings

- [high] app/web/templates/inbox/_email_notice.html:6: Failed runs display “Geen nieuwe mail met facturen gevonden.” `IntakeRunner` converts login and connection exceptions into `IntakeReport(status="fout")`, so the route’s exception handler never handles those failures. The shared notice ignores `status` and `error_message`, hiding failures in both the Inbox and settings page. → Render failed reports as an error with the Dutch error message and settings link. Add an integration test using the real runner with a failing mailbox to verify the POST redirect and rendered error.

## Nice-to-have

- app/background.py:68: Polling error deduplication handles raised exceptions, while the real runner returns error reports. Consequently, repeated login failures still produce mailbox warnings every interval. Handle returned error reports and coordinate logging so repeated identical failures are logged once; test with the real runner contract.

STATUS: DONE