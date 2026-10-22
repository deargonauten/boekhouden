from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import web
from app.web.ledger_routes import router as ledger_router
from app.web.inbox_routes import router as inbox_router
from app.web.extraction_routes import router as extraction_router
from app.web.relations_routes import router as relations_router
from app.web.company_routes import router as company_router
from app.web.vat_routes import router as vat_router
from app.domain.glossary import terms_alphabetical
from app.web.navigation import NAV_ITEMS, NavItem

router = APIRouter()
# Registered first: these nav keys are served by the ledger router, not the placeholder.
router.include_router(ledger_router)
router.include_router(relations_router)
router.include_router(company_router)
router.include_router(vat_router)
router.include_router(inbox_router)
router.include_router(extraction_router)
LEDGER_KEYS = {"boeken", "instellingen", "relaties", "inbox"}


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/inbox", status_code=307)


@router.get("/help", include_in_schema=False)
def help_page(request: Request):
    return web.templates.TemplateResponse(
        request, "help.html", web.page_context(request, title="Uitleg van termen", terms=terms_alphabetical())
    )


def _register(item: NavItem) -> None:
    def page(request: Request):
        return web.templates.TemplateResponse(
            request, "placeholder.html", web.page_context(request, title=item.label, icon_name=item.icon)
        )

    page.__name__ = f"page_{item.key}"
    router.add_api_route(item.path, page, methods=["GET"], include_in_schema=False)


for _item in NAV_ITEMS:
    if _item.key in LEDGER_KEYS:
        continue
    _register(_item)
