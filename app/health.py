from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
def health(request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error", "database": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})
