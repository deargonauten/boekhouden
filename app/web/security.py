"""App-wide same-origin guard against cross-site form posts (CSRF)."""

from urllib.parse import urlsplit

from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED_FETCH_SITES = {"same-origin", "none"}

BLOCKED_MESSAGE = (
    "Dit verzoek kwam niet van deze website. "
    "Ga terug en probeer het opnieuw vanaf de app zelf."
)

_PAGE = (
    '<!doctype html><html lang="nl"><head><meta charset="utf-8">'
    "<title>Verzoek geweigerd</title></head><body><h1>Verzoek geweigerd</h1>"
    f"<p>{BLOCKED_MESSAGE}</p></body></html>"
)


def is_cross_site(method: str, headers: dict[str, str]) -> bool:
    """True when an unsafe request demonstrably came from another site.

    Requests without Origin and Sec-Fetch-Site (curl, test clients) are allowed.
    """
    if method.upper() not in UNSAFE_METHODS:
        return False
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.lower() not in ALLOWED_FETCH_SITES:
        return True
    origin = headers.get("origin")
    if origin is not None:
        host = headers.get("host", "")
        if urlsplit(origin).netloc.lower() != host.lower():
            return True
    return False


class SameOriginMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if is_cross_site(scope["method"], headers):
                await HTMLResponse(_PAGE, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
