VERDICT: PASS
## Summary
Security review of the skeleton found nothing blocking. Defaults are safe for a local single-user app:
- Server binds to 127.0.0.1 by default (config.py, .env.example, run.sh).
- `.env` and `data/` are gitignored; `.env.example` is committed with no secrets. `ANTHROPIC_API_KEY` is a `SecretStr`.
- No user input reaches SQL, the filesystem or templates. The only routes are static nav pages, a redirect and `/health`.
- Jinja2Templates autoescapes. Template variables are server-defined nav labels. The 404 page does not echo the requested path.
- `/health` returns only a generic ok/error status, with no exception detail.
- StaticFiles is mounted on a fixed directory. htmx is vendored, so there is no CDN or third-party script at runtime.
- The SQLite engine uses parameter-free pragmas only. Migrations use the settings URL.
- Dependencies are unpinned in pyproject.toml but locked in uv.lock.

## Nice-to-have
- `APP_HOST` can be set to 0.0.0.0 with no warning. This is fine now. Once real data and uploads exist, consider a startup warning for a non-loopback host, since the app has no authentication.
- There is no Host-header or CSRF protection. That is not needed for the skeleton, but add CSRF and Origin checks when the first POST routes (uploads, bookings) land.
- `run.sh` sources `.env` with `. ./.env`, which executes shell. That is acceptable because the file is user-owned, but it will break on values with spaces or special characters.

STATUS: DONE
