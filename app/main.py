from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import web
from app.background import start_email_poller, stop_email_poller
from app.config import Settings, ensure_data_dirs, get_settings
from app.db import SessionLocal, create_db_engine
from app.domain.email_intake import IntakeRunner
from app.health import router as health_router
from app.web.security import SameOriginMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_data_dirs(settings)
        app.state.email_poller = start_email_poller(app)
        yield
        await stop_email_poller(app.state.email_poller)
        app.state.engine.dispose()

    app = FastAPI(title="Boekhouden", lifespan=lifespan)
    app.state.settings = settings
    # Engines connect lazily, so creating it here touches no file.
    app.state.engine = create_db_engine(settings)
    # One runner per app: the button and the background poller share its lock.
    app.state.email_runner = IntakeRunner(
        settings, session_factory=partial(SessionLocal, bind=app.state.engine)
    )
    app.state.email_poller = None

    app.add_middleware(SameOriginMiddleware)
    app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")
    app.include_router(health_router)
    app.include_router(web.router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        wants_json = "application/json" in request.headers.get("accept", "")
        if exc.status_code == 404 and not wants_json:
            return web.not_found_response(request)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
