VERDICT: REWORK

## Summary
The deletion flow clearly identifies the file, warns that deletion is permanent, offers cancellation, and uses existing UI components. Review was based on code and the supplied result of 1707 passing tests; visual browser verification was unavailable.

## Blocking findings
- [P2] app/web/templates/inbox/delete.html:21: The booked-document alert tells users to make a “stornoboeking” without explaining that term. Only “bewaarplicht” has a glossary tooltip on this page. This violates CLAUDE.md’s requirement that every bookkeeping term have an explanation and leaves inexperienced users unclear about the suggested remedy. Add plain Dutch guidance such as “Een boeking ongedaan maken” alongside `info("storno")`, using the existing central glossary entry, for both GET and rejected POST states.

## Nice-to-have
- app/web/templates/inbox/list.html:94: Booked rows omit the delete action without the explanatory hint specified in AC 11. The detail page provides that explanation, so this is not blocking; adding it to the row would make the restriction easier to discover.

STATUS: DONE