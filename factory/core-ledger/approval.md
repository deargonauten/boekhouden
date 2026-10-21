VERDICT: APPROVE

## Reasoning
Process was followed. The spec was approved, four parts (a-d) were built and integrated, and round 1 ran four reviews. Code, security and ui passed. ux returned one medium REWORK: 4xx responses on the fiscal-year forms were swallowed by hx-boost. Round 2 fixed it with a global `htmx:beforeSwap` handler (409/422 only) in base.html plus a test, and the ux re-review passed. The round-2 delta was small and did not touch domain code, so skipping the other reviewers is reasonable.

I ran `uv run pytest` on the branch: 202 passed, 1 warning (a starlette/httpx deprecation). Spot-checks:
- Money is int cents, and `money.py` rejects bool and non-int.
- `migrations/versions/0002_core_ledger.py` contains the `RAISE(ABORT` triggers for immutability and period locks.
- The handler is present in `app/web/templates/base.html`.
- The code reviewer confirmed gapless sequence numbers (savepoint), the storno guards, and routes that only parse and delegate.

## Acceptance criteria check
Spec has 27 criteria. The code reviewer verified all 27 against the integrated branch and I spot-checked the main ones.
- Money and validation (1-4): met.
- Posting, period locks, immutability triggers, storno (5-10): met.
- Grootboekschema, seed and account rules (11-13): met.
- Dagboeken (14-15): met.
- Boekjaar, periods, one-way locking, trial balance (16-19): met.
- UI routes /boeken, /boeken/nieuw, /boeken/{id}, /instellingen/* (20-23): met.
- `euro` filter, thin routes and error mapping (24-27): met per the reviews and tests.

## Outstanding issues
Non-blocking nice-to-haves only:
- System accounts such as debiteuren and btw can be deactivated, which could break later features that post to them.
- The htmx handler test checks the script text only, not browser behaviour.
- The ui review did not run the app in a browser.

## What the human should look at (if HUMAN_REVIEW)
Not required. Optionally, click through /boeken/nieuw and /instellingen/boekjaren once in a browser. In particular, check that creating a duplicate year shows the Dutch error.

STATUS: DONE
