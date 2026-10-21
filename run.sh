#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p data

# Load .env so APP_HOST/APP_PORT/APP_RELOAD apply to uvicorn too.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

uv run alembic upgrade head

args=(app.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}")
if [ "${APP_RELOAD:-true}" = "true" ]; then
  args+=(--reload)
fi
exec uv run uvicorn "${args[@]}"
