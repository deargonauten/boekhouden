from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import web
from app.web.navigation import NAV_ITEMS, NavItem

router = APIRouter()


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/inbox", status_code=307)


def _register(item: NavItem) -> None:
    def page(request: Request):
        return web.templates.TemplateResponse(
            request, "placeholder.html", web.page_context(request, title=item.label)
        )

    page.__name__ = f"page_{item.key}"
    router.add_api_route(item.path, page, methods=["GET"], include_in_schema=False)


for _item in NAV_ITEMS:
    _register(_item)
