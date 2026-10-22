VERDICT: REWORK

## Summary
Money sign rules, atomic corrections, append-only storage, and same-origin protection look sound. One confirmed race violates AC 7 and can double the opening balance. Used the supplied full-suite result; ran one targeted in-memory reproduction.

## Blocking findings
- [high] app/domain/opening/service.py:371: The active entry is read before `_open_transaction` acquires SQLite’s write lock. Two overlapping initial submissions can both see no existing opening balance and subsequently commit separate entries. Reproduced by completing a second submission between the first submission’s lookup and transaction acquisition: two opening entries persisted, the ledger showed 20,000 cents, and the form showed only 10,000 cents. Acquire the write lock before reading the active entry and checking replacement eligibility, keeping those checks and writes in the same transaction. Add a regression test with two interleaved sessions proving only one active opening entry remains.

## Nice-to-have
None.

STATUS: DONE