import itertools
from urllib.parse import urlencode
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.domain.glossary import get_term
from app.domain.money import format_euro
from app.web.navigation import GROUP_LABELS, NAV_ITEMS, mark_active

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["euro"] = format_euro
_info_ids = itertools.count(1)  # tooltip ids only need to be unique within one response
templates.env.globals["explain"] = get_term
templates.env.globals["next_info_id"] = lambda: next(_info_ids)
templates.env.globals["group_labels"] = GROUP_LABELS


def page_url(base_url: str, params: dict, page: int) -> str:
    """Pager link: keep the non-empty params; page 1 carries no `page` parameter."""
    query = [(k, v) for k, v in params.items() if v not in (None, "")]
    if page > 1:
        query.append(("page", page))
    return f"{base_url}?{urlencode(query)}" if query else base_url


templates.env.globals["page_url"] = page_url


def _template_error(message: str):
    raise ValueError(message)


templates.env.globals["template_error"] = _template_error  # e.g. icon() with an unknown name


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
