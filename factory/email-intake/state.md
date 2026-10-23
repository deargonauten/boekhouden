# email-intake
Step: 3 Review round 1
Branch: factory/email-intake (base main)
Tests: .venv/bin/python -m pytest -q -> 2617 passed, 1 deselected (3 poller test fixes then re-run of email tests: 99 passed), 2026-10-23
Known nice-to-have: no stop flag for in-flight run on shutdown (per-mail commits make it safe)
