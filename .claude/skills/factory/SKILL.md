---
name: factory
description: Software factory. Runs a feature through spec → parallel build in worktrees → multi-reviewer review → approval. Use as `/factory next` (take the next item from backlog.md) or `/factory <feature description>`.
---

# Software Factory

You are the **orchestrator**. You do not write the spec, the feature code or the reviews yourself; you spawn subagents for that, route questions, merge results and keep state. Role prompts live in `.claude/skills/factory/roles/`.

## Invocation

- `/factory next` → open `backlog.md`, take the first `- [ ]` item, set it to `[~]`.
- `/factory <description>` → run on the fly. If the description matches a backlog item, use that item; otherwise do not touch the backlog.
- Anything else / empty → ask what to build.
- If a `factory/<slug>/state.md` already exists for the feature, **resume** from the recorded step instead of restarting.

## Working directory per feature

`factory/<slug>/` (slug = kebab-case of the feature title):

```
state.md                 current step, round counters, branch names, open questions
spec.md                  the spec (step 1)
build/round-N/<builder>.md   builder reports
reviews/round-N/{security,ux,ui,code}.md   (ux and ui may be one file, `ux-ui.md`)
approval.md              approver verdict
```

Update `state.md` after every step so the run can be resumed.

## Preflight

1. Worktrees need git. If the folder is not a git repo: `git init`, add a `.gitignore`, make an initial commit. Tell the user once.
2. If the working tree is dirty, commit it as `factory: baseline` (or ask if it looks like unrelated user work).
3. Create branch `factory/<slug>` from the current branch. All integration happens there.

## Token budget (important)

A run costs roughly the sum of every agent's cold start (CLAUDE.md + spec + code reads) plus repeated test runs. Keep it lean:

- **Fewest agents that work.** Default to at most **3 builders**; merge small or dependent parts (schema + domain + glossary is one builder; each web area another). Only split further when parts are large and truly independent.
- **Models (hard rule): never use opus.** Always pass `model` explicitly: `sonnet` for the spec writer, builders (including money/VAT and migrations) and reviewer fallbacks; `haiku` for the approver and for trivial builders. Never omit `model` (the default may be opus). Opus only in very specific cases, and only after the user has explicitly agreed for that case.
- **Tests run once per stage, by the orchestrator.** Builders run only their own tests plus the full suite once before finishing. Reviewers and the approver do **not** rerun the full suite; they read the orchestrator's last result (put it in `state.md`: command, count, date) and run only targeted tests if they need to verify a specific claim.
- **Narrow prompts.** Give each agent only the spec sections and files it needs (its part, acceptance criteria it covers, owned files), not "read everything". Tell reviewers to review `git diff <base>...HEAD` and open other files only to verify a finding.
- **Wave by dependency, but don't over-wave.** Small schema parts that everything depends on belong in the same builder as the domain code that uses them.

## Communication rules (important)

Subagents cannot talk to the user and cannot talk to each other directly. Everything goes through you:

- Every subagent must end its reply with either `STATUS: DONE` or a `QUESTIONS:` block (numbered, each tagged `[business]` or `[technical]`, with a recommended default).
- **Questions to the user:** relay them with AskUserQuestion (batch them, include the recommended default). Never invent business answers.
- **Builder → spec writer:** when a builder returns a `[spec]` question, resume the spec writer (SendMessage to its agent id, or respawn it with spec.md + the question) to answer it. If the spec writer says it needs a business decision, ask the user. Update `spec.md` if the answer changes the spec, then resume the builder (SendMessage) with the answer.
- Keep agent ids in `state.md` so you can resume them.

## Step 1 — Spec (skip if `factory/<slug>/spec.md` exists and is marked `Status: APPROVED`)

Spawn one **spec writer** (`roles/spec-writer.md`). Give it: the feature text, repo context pointers, and a request to write `factory/<slug>/spec.md`. It may spawn its own research subagents in parallel (codebase exploration, library/API checks, prior art). If it returns `QUESTIONS:`, relay them to the user, then resume it with the answers. Repeat until it reports `STATUS: DONE` and the spec has `Status: APPROVED`.

The spec must contain: goal, non-goals, user stories, acceptance criteria (testable), technical approach, **a work breakdown into independent parts with the files/areas each part owns**, and open risks.

Show the user a short summary of the spec (not the whole file) and the path. Proceed unless they object; if the feature is large or ambiguous, ask for an explicit go.

## Step 2 — Build

1. Read the work breakdown in `spec.md`. Parts must have disjoint file ownership; if they overlap, ask the spec writer to re-split, or merge those parts into one builder.
2. Group the parts into at most 3 builders (see Token budget). Spawn them **in parallel** where independent (otherwise in dependency order), each with `isolation: "worktree"` (`roles/builder.md`). Each gets: its part(s) and the spec sections it needs, and its owned files. Builders write tests first where the repo has a test setup, commit on their own worktree branch, and write `build/round-N/<builder>.md` (what was done, deviations, anything the integrator must know).
3. Handle builder `QUESTIONS:` per the communication rules above.
4. **Integrate:** merge each builder branch into `factory/<slug>`, resolve conflicts yourself (prefer the spec as tiebreaker), run the project's tests/build/lint, fix integration breakage. Remove the worktrees afterwards. If integration needs real feature work, spawn a builder for it rather than doing it silently.

## Step 3 — Review (max 2 review rounds)

**Reviews are done by Codex, not by Claude subagents.** For each lens, run from the repo root (on the integrated branch):

```
mkdir -p factory/<slug>/reviews/round-N
codex exec -s read-only --ephemeral -C "$PWD" -o factory/<slug>/reviews/round-N/<lens>.md - <<'PROMPT'
<contents of roles/reviewer.md> + lens + base branch + test result from state.md + review calibration + (round 2) prior REWORK findings
PROMPT
```

`-o` writes Codex's final message to the review file (the sandbox stays read-only). With several lenses, run them in parallel via `run_in_background` and give each a generous `timeout`. Check that the first line of each file is `VERDICT: PASS` or `VERDICT: REWORK`; if it is not, or `codex` is missing or fails, re-run once, then fall back to a `model: "sonnet"` reviewer subagent and tell the user. Codex receives the repo diff, so this sends code to an external service; the user asked for this. Everything below (lenses, calibration, rounds) is unchanged.

Lens setup: reviewers run in parallel, read-only, each on the integrated branch (`roles/reviewer.md`). Default to **three** reviewers: `security`, `code`, and one combined `ux-ui` reviewer (covers both lenses; writes `ux-ui.md`). Skip lenses that do not apply (write PASS (n/a) yourself, no agent needed): no UI → no `ux-ui`; no input handling, auth, data exposure or new routes → fold `security` into `code`. For a small diff (roughly under 300 changed lines) use a single reviewer covering all applicable lenses. Each writes `reviews/round-N/<lens>.md` with a first line `VERDICT: PASS` or `VERDICT: REWORK`, followed by findings. Tell them the test result from `state.md` and not to rerun the full suite.

Review calibration (state this in every reviewer prompt): be realistic. Only REWORK for issues that would genuinely hurt: broken acceptance criteria, real vulnerabilities, clear usability failures, bugs, maintainability traps. Style nits and speculative concerns go in a `Nice-to-have` section and do **not** justify REWORK. "Nothing to report" with PASS is a perfectly good review. Skip a lens that does not apply (e.g. `ui`/`ux` for a pure backend feature) by writing PASS (n/a).

Each REWORK finding must include: severity, location, what is wrong, and what done looks like.

- All PASS → go to step 4.
- Any REWORK and review round < 2 → collect only the REWORK findings (not nice-to-haves), spawn builders (worktrees again, split by file ownership) to fix them, integrate, run review round 2. Reviewers in round 2 verify prior findings were fixed and look at the delta; they should not raise new nice-to-haves as blockers.
- Any REWORK after round 2 → go to step 4 anyway, with the outstanding findings listed.

## Step 4 — Approval

Spawn one **approver** (`roles/approver.md`, `model: "haiku"`; use `sonnet` if review findings were mixed). It reads spec, build reports, review verdicts and the test result in `state.md`, and walks the acceptance criteria as a checklist, spot-checking code only where a criterion is unclear. It does not rerun the full suite. It writes `approval.md` with `VERDICT: APPROVE` or `VERDICT: HUMAN_REVIEW` and its reasoning. Outstanding REWORK findings after round 2 should normally lead to HUMAN_REVIEW, unless it judges them acceptable.

- **APPROVE** → finish (below).
- **HUMAN_REVIEW** → present to the user: summary, what the approver is unsure about, branch name, how to run it, links to the review files. Ask: approve, or rework (with their feedback).
  - Rework → feed the feedback to builders (step 2, as a new build round), integrate, then a fresh review (step 3) and approver. **Human-triggered rework is limited to 2 rounds.** After the 2nd, present the result and let the user decide to accept, or stop and leave it `[~]`.

## Finish

1. Merge `factory/<slug>` into the original branch (fast-forward or merge commit), unless the user prefers a PR.
2. Mark the backlog item `[x]` with the date, or add it under completed if it was ad hoc.
3. Set `state.md` to `COMPLETED`.
4. Report to the user in a few lines: what was built, branch/commit, review outcomes, anything deferred (nice-to-haves).

## Guardrails

- Never skip a step, and never mark `[x]` before approval.
- Round counters live in `state.md`; respect the caps.
- Ask the user only for genuine business decisions or when a subagent is blocked. Resolve technical choices with sensible defaults and record them in the spec.
- Do not re-read files or rerun the full suite without a reason; each repeat costs tokens.
- Keep your own messages to the user short: one line per step transition.
