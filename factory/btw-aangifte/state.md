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
