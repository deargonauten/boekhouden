VERDICT: PASS

## Summary
Both prior blocking findings are resolved. The write lock now precedes the active-entry lookup and replacement checks, with an interleaved-session regression test. Technical account rows now lead with plain Dutch labels and include glossary-backed explanations and accessible input labels.

Reviewed the rework delta across code, security, UX and UI. No new blocking issues found. Accepted the supplied result of 1818 passed, 1 deselected; did not rerun the suite. Visual layout assessed from code.

## Nice-to-have
- app/web/opening_routes.py:159: Give accounts 1410, 3130 and 3140 more specific glossary labels. “De klant rekent de BTW af” does not distinguish recoverable from payable reverse-charge VAT, and the explanation for 3140 discusses sales rather than private use.

STATUS: DONE