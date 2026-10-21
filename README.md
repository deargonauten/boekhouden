# Boekhouden

Local, single-user Dutch bookkeeping for an eenmanszaak/VOF. See `CLAUDE.md` for decisions and compliance rules.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (plain `pip install -e .` also works)

## Quick start

```sh
./boekhouden          # setup + migrate + start
./boekhouden update   # git pull, deps, migrate
./boekhouden test     # pytest
./boekhouden help
```

## Setup

```sh
uv sync
cp .env.example .env
```

## Run

```sh
./run.sh
```

Creates `data/` if needed, applies migrations (`alembic upgrade head`) and starts the app on http://127.0.0.1:8000 (`APP_HOST`, `APP_PORT`, `APP_RELOAD` in `.env`). Health check: `/health`.

## Tests

```sh
uv run pytest
```

Tests use a temporary database and never touch `data/boekhouden.db`.

## Migrations

```sh
uv run alembic revision -m "describe change"
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic check
```

## Project layout

```
app/main.py        create_app() factory, lifespan, static, routers, 404 handler
app/config.py      Settings (.env), get_settings(), ensure_data_dirs()
app/db.py          SQLAlchemy engine (SQLite PRAGMAs), Base, SessionLocal, get_session
app/health.py      /health
app/domain/        business logic; no FastAPI/HTTP imports
app/web/           Jinja2 + HTMX UI (navigation, routes, templates, static)
migrations/        Alembic (env.py takes the URL from Settings)
tests/             pytest
```

## Data

Everything lives under `data/` (SQLite database incl. `-wal`/`-shm` files, and `data/documents/`). It is never committed. Back it up: bookkeeping records must be kept for 7 years.
