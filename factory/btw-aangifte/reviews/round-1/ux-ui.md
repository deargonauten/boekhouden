VERDICT: REWORK

## Summary

The screens reuse existing interface components and explain the main filing flow clearly. Two issues could mislead users about what to submit. Reviewed `git diff main...HEAD`; relied on the supplied test result (2476 passed, 1 deselected). Browser verification was blocked by a tool sandbox error, so visual layout remains unverified.

## Blocking findings

- [high] app/domain/vat/export.py:92 and :181: Both exports omit `snapshot.icp_unassigned`. If all EU sales lack a linked customer, the CSV contains only headers and the PDF incorrectly says “Geen EU-verkopen in deze periode.” Users relying on these exports could omit actual EU sales from their submission. → Preserve the unassigned amounts visibly in the exports, identify the missing customer details, and explain that customers must be linked before completing the ICP-opgaaf.

- [medium] app/web/templates/btw/return.html:26: An empty period fully covered by KOR shows both “je hoeft geen btw-aangifte te doen” and “Je moet toch een aangifte doen”. The same instruction also appears after an empty return has already been filed. → Show the instruction to submit a nil return only for an unfiled period outside full KOR coverage; use appropriate informational wording for filed periods.

## Nice-to-have

- app/web/templates/btw/return.html:55: Give “Verschuldigde btw” a plain Dutch label and the existing `btw_af_te_dragen` glossary explanation.
- app/web/templates/btw/confirm.html:14: Name the months being locked instead of showing only their count, so users can verify the irreversible action directly.

STATUS: DONE