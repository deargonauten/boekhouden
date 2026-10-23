# btw-aangifte
Step: 1 (spec)
Review round: 0
Human rework rounds: 0
Base branch: main
Branch: factory/btw-aangifte
Spec: APPROVED (writer a6382899f9da00bac). Step 2 wave 1 = builder A; wave 2 = B + C parallel.
A merged (2382 passed, 1 expected glossary-usage failure until B). Wave 2: B + C started.
C merged (2440 passed, 1 expected glossary failure). Waiting for B (kind values: quarter|month|kwartaal|maand).
Integrated A+B+C. Tests: .venv/bin/python -m pytest -q -> 2476 passed, 1 deselected (2026-10-23). Step 3 review round 1 starting (codex). Base: main
Review round 1: security PASS, code REWORK (3), ux-ui REWORK (2). Fix builders D (filing.py, report.py) and E (export.py, return.html) started.
E merged (2483 passed on E branch). Waiting for D.
D merged. Tests: .venv/bin/python -m pytest -q -> 2485 passed, 1 deselected (2026-10-23). Review round 2 started (delta since e16e3c8).
Review round 2: PASS. Step 4 approver started.
Step 4: approver HUMAN_REVIEW (rounding of omzet to verify, ICP CSV format unverified, browser check of /btw). Awaiting user.
Human rework 1: F merged (final amount rounding). Tests 2506 passed (builder F full run, 2026-10-23). Review round 3 (delta since f565de4).
Review round 3: PASS. Awaiting user approval after human rework 1.
