Step: 1 spec
Branch: factory/openingsbalans (base main)
Rounds: build 0, review 0
Step: 2 build (A then B)
A merged (c7f42b3). Step: build B
Step: 3 review round 1. Tests: .venv/bin/python -m pytest -q → 1808 passed, 1 deselected (2026-10-22), base main
Review round 1: both REWORK (race in book_opening_balance; plain-language labels). Step: rework build round 2
Rework merged (6e85ac7). Tests: 1818 passed, 1 deselected (2026-10-22). Step: review round 2
COMPLETED
