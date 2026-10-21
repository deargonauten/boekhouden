Status: APPROVED

# Spec: Project skeleton

## Goal and context
Create the runnable foundation for Boekhouden (local single-user Dutch bookkeeping, see CLAUDE.md): a FastAPI app serving a Jinja2 + HTMX UI with a MoneyMonk-style sidebar, SQLite via SQLAlchemy + Alembic (empty baseline), pytest, `.env` settings, and a run script. The repo has no code yet. No ledger/domain features; only the structure later features plug into.

## Non-goals
- No tables, models with business meaning, grootboek seed, auth, Claude API calls, IMAP, upload handling, or any real page content.
- No Docker, no JS build step (HTMX and CSS are vendored static files or plain CSS; no npm).
- No CI config, no linting setup beyond what is listed.

## User stories
- As the user I run one command and open http://127.0.0.1:8000 to see the app with a sidebar of Dutch sections.
- As the user I click any sidebar item and get a placeholder page in the same layout, with the active item highlighted.
- As a developer I run `pytest` and `alembic upgrade head` on a fresh clone and both work.

## Acceptance criteria
1. `uv sync` (pyproject.toml, Python >=3.12, lockfile committed) installs all deps; runtime: fastapi, uvicorn[standard], jinja2, sqlalchemy>=2, alembic, pydantic-settings, python-multipart; dev group: pytest, httpx.
2. `./run.sh` (executable, `set -euo pipefail`) creates `data/` if missing, runs `alembic upgrade head`, then starts uvicorn on `APP_HOST:APP_PORT` (defaults 127.0.0.1:8000) with `--reload` when `APP_RELOAD=true` (default true). It works from any cwd (cd's to repo root).
3. `GET /health` returns 200 JSON `{"status":"ok","database":"ok"}` after executing `SELECT 1` against the SQLite DB; if the DB check fails returns 503 with `{"status":"error","database":"error"}`.
4. `GET /` redirects (307) to `/inbox`.
5. Each of these routes returns 200 HTML rendered in the base layout, with the Dutch page title as `<h1>` and a short "Deze pagina is nog in ontwikkeling." placeholder:
   `/inbox` Inbox, `/boeken` Boeken, `/bank` Bank, `/verkoop` Verkoop, `/inkoop` Inkoop, `/relaties` Relaties, `/btw` BTW, `/rapportages` Rapportages, `/activa` Activa, `/instellingen` Instellingen.
6. The sidebar (rendered in `base.html` from a single Python list of `NavItem(label, path, key)`) shows all ten entries in the order above, grouped visually: Inbox/Boeken/Bank | Verkoop/Inkoop/Relaties | BTW/Rapportages/Activa | Instellingen (pinned at bottom). The entry whose path prefixes the request path has `aria-current="page"` and an `active` CSS class. App name "Boekhouden" in the sidebar header. `<html lang="nl">`.
7. Layout is responsive: sidebar fixed left on >=768px, collapses behind a toggle button (CSS-only checkbox or minimal inline JS) on narrow screens. Base template loads `/static/htmx.min.js` (vendored, version pinned, noted in a comment) and `/static/app.css`. No external CDN requests at runtime.
8. HTMX boost: `<body hx-boost="true">`, so nav clicks swap the body without full reload (full-page fallback still works without JS).
9. Unknown path returns a 404 page rendered in the base layout (Dutch: "Pagina niet gevonden").
10. Settings (`app/config.py`, `pydantic-settings`, `Settings` class, `get_settings()` cached): `DATABASE_PATH` (default `data/boekhouden.db`, resolved relative to repo root), `DOCUMENTS_DIR` (default `data/documents`), `APP_HOST`, `APP_PORT`, `APP_RELOAD`, `ANTHROPIC_API_KEY` (optional, `SecretStr | None`, unused for now), `IMAP_*` NOT included yet. Loaded from `.env` at repo root; env vars override. `.env.example` committed with all keys and comments; `.env` already gitignored.
11. `ensure_data_dirs(settings)` creates the parent of the DB file and `DOCUMENTS_DIR` (idempotent); called at app startup (lifespan) and by `run.sh` indirectly via the app. `.gitignore` is extended with `data/` (except nothing inside is committed), `__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`.
12. DB engine (`app/db.py`): SQLAlchemy 2 sync engine on `sqlite:///<DATABASE_PATH>`; on every connection set `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`. Provides `Base` (DeclarativeBase), `SessionLocal`, and a FastAPI dependency `get_session()`.
13. Alembic is configured (`alembic.ini`, `migrations/env.py`) to take the URL from `Settings` (not hardcoded), with `target_metadata = Base.metadata` and `render_as_batch=True` (SQLite). One baseline revision `0001_baseline` exists with empty `upgrade()`/`downgrade()`. `alembic upgrade head` on a fresh checkout creates `data/boekhouden.db` and the `alembic_version` table; `alembic downgrade base` and `alembic check` succeed.
14. Package layout exists with `__init__.py`: `app/`, `app/domain/` (empty, with docstring stating "business logic lives here; no FastAPI/HTTP imports"), `app/web/`. No logic in route handlers beyond rendering/health.
15. `pytest` passes from repo root with tests listed under Test strategy; tests never touch `data/boekhouden.db` (use tmp DB via env/settings override).
16. `README.md` (Dutch headings ok, English body ok) documents: prerequisites (Python 3.12+, uv), setup (`uv sync`, `cp .env.example .env`), run (`./run.sh`), tests (`uv run pytest`), migrations (`uv run alembic revision -m ...`, `upgrade head`), project layout, and where data lives (`data/`, never committed, back it up).

## Technical approach
Layout:
```
pyproject.toml  uv.lock  run.sh  alembic.ini  .env.example  README.md
app/__init__.py
app/main.py          create_app() factory + module-level `app`; lifespan -> ensure_data_dirs; mounts /static; includes web router + health router; 404 handler
app/config.py        Settings, get_settings, ensure_data_dirs
app/db.py            engine factory (create_db_engine(settings)), Base, SessionLocal, get_session
app/health.py        APIRouter with /health
app/domain/__init__.py
app/web/__init__.py  exports `router`, `templates`
app/web/navigation.py NavItem dataclass, NAV_ITEMS, helper to mark active
app/web/routes.py    "/" redirect + one generic placeholder route per nav item (loop over NAV_ITEMS; handler only renders template)
app/web/templates/base.html, placeholder.html, 404.html, partials/sidebar.html
app/web/static/app.css, htmx.min.js
migrations/env.py, migrations/script.py.mako, migrations/versions/0001_baseline.py
tests/conftest.py, tests/test_health.py, tests/test_config.py, tests/test_db.py, tests/test_migrations.py, tests/test_web.py
```
- `create_app(settings: Settings | None = None)` so tests can inject settings; engine is stored on `app.state.engine`; `get_session` reads it from `request.app.state`.
- Templating: `Jinja2Templates(directory=app/web/templates)` exposed by `app.web`; every page gets `nav_items` and `current_path` via a small context helper; active detection: `path == item.path or path.startswith(item.path + "/")`.
- Health router lives outside `app/web` and has no layout.
- Settings path resolution: relative paths resolved against repo root (`Path(__file__).parents[1]`), so cwd does not matter.
- Python 3.12 pinned via `requires-python = ">=3.12"` and `.python-version` containing `3.12`.
- Styling: plain CSS with custom properties, light theme with `prefers-color-scheme: dark` support; keep it clean and MoneyMonk-like (dark-ish sidebar, light content). Currency/number formatting is out of scope.

Error handling: DB failure in `/health` -> 503 as above (no stack trace in body). Missing `.env` is fine (defaults apply).

## Work breakdown
Two parts, disjoint files, buildable in parallel.

**Part A: backend, config, DB, migrations, tooling** (owner of everything not under `app/web/`)
Files: `pyproject.toml`, `uv.lock`, `.python-version`, `run.sh`, `alembic.ini`, `.env.example`, `.gitignore` (edit), `README.md`, `app/__init__.py`, `app/main.py`, `app/config.py`, `app/db.py`, `app/health.py`, `app/domain/__init__.py`, `migrations/**`, `tests/conftest.py`, `tests/test_health.py`, `tests/test_config.py`, `tests/test_db.py`, `tests/test_migrations.py`.
Covers AC 1-3, 10-16 (README sections about layout may reference B's files by the paths above).

**Part B: web UI** (owner of `app/web/**` and `tests/test_web.py`)
Files: `app/web/__init__.py`, `navigation.py`, `routes.py`, `templates/**`, `static/**`, `tests/test_web.py`.
Covers AC 4-9.

Integration points (the contract):
- B exports from `app.web`: `router` (APIRouter, includes `/` redirect and the placeholder routes), `templates` (Jinja2Templates), `STATIC_DIR` (Path to `app/web/static`), and `not_found_response(request)` returning the rendered 404 `HTMLResponse` with status 404.
- A's `app/main.py` does `app.include_router(web.router)`, `app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")`, and registers a 404 exception handler that calls `web.not_found_response` for non-JSON requests.
- A's `conftest.py` provides a `client` fixture (`TestClient(create_app(test_settings))` with tmp DB path, migrations applied); B's tests use that fixture. Until A lands, B may test with a local `TestClient` on a minimal app including `web.router`; final merge uses the shared fixture.
- Only A edits `app/main.py`; only B edits anything under `app/web/`.

## Test strategy
(Skeleton has no money/VAT logic, so no TDD-by-domain requirement; still write tests alongside.)
- `test_health`: 200 + body ok; 503 when engine points to an unusable path (monkeypatch/dispose broken engine).
- `test_config`: defaults; env override of `DATABASE_PATH`; relative path resolved against repo root; `ensure_data_dirs` creates dirs and is idempotent; API key not leaked in `repr`.
- `test_db`: PRAGMAs foreign_keys=1, journal_mode=wal, on a fresh connection; `get_session` yields a working session.
- `test_migrations`: run `alembic upgrade head` programmatically against a tmp DB -> `alembic_version` holds `0001_baseline`; `downgrade base` works; `alembic check` reports no drift.
- `test_web`: parametrized over all ten routes (200, h1 text, sidebar contains all labels in order, exactly one `aria-current="page"` on the right item); `/` redirects to `/inbox`; `/static/app.css` and `/static/htmx.min.js` served; unknown path -> 404 with layout and "Pagina niet gevonden"; `lang="nl"`.
- Manual smoke (reviewer): `./run.sh`, open in browser, click through sidebar, resize to narrow width.

## Risks and decisions made
- Sync SQLAlchemy 2 (not async): single-user local app on SQLite; simpler, fewer pitfalls with Alembic. Handlers using it are plain `def` (run in threadpool).
- SQLAlchemy chosen as ORM/metadata layer because Alembic autogenerate and `alembic check` depend on it; domain code can still use Core where better.
- uv for dependency management (installed locally); `requirements` files not kept. README notes plain `pip install -e .` also works.
- WAL mode creates `-wal`/`-shm` files next to the DB; all under gitignored `data/`. Backup feature (later backlog item) must account for it.
- HTMX vendored to keep the app offline-capable and avoid CDN dependency; version pinned in a header comment.
- Placeholder routes generated from one list so later features replace a nav entry's route without touching layout code.
- Nav order/labels mirror the backlog; Inkoop/Relaties/Activa added beyond the user's list because backlog features (purchase booking, relations, fixed assets) need homes. Dashboard is not a nav item yet (home is Inbox until the Dashboard feature lands).
- Local Python is 3.15 but project targets 3.12+; `.python-version` pins 3.12 so uv provisions the right interpreter.
