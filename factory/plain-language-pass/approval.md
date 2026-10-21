VERDICT: APPROVE

## Reasoning
Process followed: spec approved, parts A/B/C integrated on the branch, review round 1 run (code, security, ui, ux), all four PASS, no REWORK findings. Part A/B build reports are missing (lost with their worktrees), but the diff shows their deliverables: glossary.py, _info.html, sidebar/nav changes, suggestions.py, reworded domain messages, and tests. I ran `uv run pytest -q` on the branch: 341 passed. The diff has no model, migration, route or error-code changes, and money stays in integer cents. Enforcement tests (test_plain_language.py, web_helpers.py, message lint, glossary quality gate) are in place, so later features cannot regress silently.

## Acceptance criteria check
- A Glossary (items 1-4, 27): met (glossary.py plus test_glossary.py, passing).
- B Info component (5-7, 24): met (macros, `explain` global, CSS-only tooltip, test_info_component.py).
- C Sidebar (8-9): met (term_key, sub-line, title).
- D Screens (10-17): met per the UX and code reviews, which rendered all ledger screens.
- E Plain-Dutch errors (18-20): met (test_error_messages.py and test_messages_text.py; old assertions updated).
- F-bis Helpers and defaults (21-22, 25): met (suggestions.py exported; MEM preselected, "Geen btw" first option, suggested code and year).
- G Enforcement tests (23-28): met. The suite is green.

## Outstanding issues
Nice-to-haves only, none blocking:
- The tooltip is anchored to `.content`, not to the icon, so it can appear far from the icon. There is also no Escape-to-dismiss, and the icon is a small touch target.
- The unbalanced-entry message puts the totals in brackets after the final full stop.
- The BTW select on the new-booking form shows "Geen btw" twice, shows raw codes such as EU_DIENSTEN, and lists rare options before 21% and 9%.
- `_default_cash_account` matches accounts by name substring, which is fragile.
- `next_info_id` is a process-global counter (cosmetic).
- No up-front hint on the new-booking form when no boekjaar exists.

## What the human should look at (if HUMAN_REVIEW)
Not required. Optionally, check the tooltip placement and the wording at 360px in a browser. The reviewers read the CSS and rendered HTML but did not run a browser.

STATUS: DONE
