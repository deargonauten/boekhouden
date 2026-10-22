# sales-invoices
Step: 1 (spec)
Review round: 0
Human rework rounds: 0
Base branch: main
Branch: factory/sales-invoices
Step: 2 (build) wave 1 = builder A
Spec: APPROVED (spec writer a30e4c25fd669631f)
Tests baseline: see below
Wave 2: C merged (2132 passed on C branch). B resumed after rate limit, pending.
Step 2 done: A, B, C merged into factory/sales-invoices. Worktrees removed.
Tests: .venv/bin/python -m pytest -q -> 2210 passed, 1 deselected (2026-10-22)
Step 3: review round 1 starting. Base: main
Step 3 review round 1: security PASS, code REWORK (3), ux-ui REWORK (1). Fix builders D (service.py) and E (edit.html/confirm) started.
Round-2 fixes: E merged (2217 passed on E branch). D pending.
Round-2 fixes D,E merged. Tests: .venv/bin/python -m pytest -q -> 2222 passed, 1 deselected (2026-10-22). Review round 2 started.
Step 4: approver HUMAN_REVIEW (browser check of htmx due date, AC30 layout, visual check). Awaiting user.
Human rework 1: F merged. Tests 2228 passed (2026-10-23). Review round 3 (ux-ui delta since 54cd87d).
G merged. Tests 2229 passed (builder G full run). Awaiting user approval after human rework 1.
