import itertools
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.domain.glossary import get_term
from app.domain.money import format_euro
from app.web.navigation import NAV_ITEMS, mark_active

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["euro"] = format_euro
_info_ids = itertools.count(1)  # tooltip ids only need to be unique within one response
templates.env.globals["explain"] = get_term
templates.env.globals["next_info_id"] = lambda: next(_info_ids)


def page_context(request: Request, **extra) -> dict:
    return {
        "nav_items": mark_active(request.url.path),
        "current_path": request.url.path,
        **extra,
    }


def not_found_response(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "404.html", page_context(request), status_code=404
    )


from app.web.routes import router  # noqa: E402

__all__ = ["router", "templates", "STATIC_DIR", "not_found_response", "NAV_ITEMS"]
