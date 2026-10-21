VERDICT: REWORK
## Summary
Code is clean and matches the spec closely. `uv run pytest`: 27 passed. AC 1, 3-16 verified against code and tests. AC 2 fails on one point: `run.sh` is not executable.

## Blocking findings
- [medium] run.sh (git mode 100644): AC 2 requires `./run.sh` to be executable, and the README tells the user to run `./run.sh`. The file is committed without the exec bit, so `./run.sh` fails with "permission denied" on a fresh clone. Fix: `chmod +x run.sh` and commit the mode change (`git update-index --chmod=+x run.sh`). The script content is otherwise correct (set -euo pipefail, cd to repo root, mkdir data, alembic upgrade, optional --reload, .env loaded).

## Nice-to-have
- The `app/web/__init__.py` import of `routes` at the bottom (circular import workaround, `noqa: E402`) works but is fragile; moving `page_context`/`templates` into a small module would remove it.
- `run.sh` sources `.env` with the shell, so values with spaces or special characters need quoting; fine for the current keys.
- Tests emit a Starlette deprecation warning about httpx (`httpx2`); harmless now.
- 404 handler also swallows non-404 HTTP errors into JSON; correct, just worth knowing when adding routes.
STATUS: DONE
