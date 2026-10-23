"""Routes for the e-mail intake UI: fetch button, settings page, connection test.

No intake logic lives here; see app.domain.email_intake. The runner is created in
app.main and found on app.state.email_runner.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session

try:  # Part A of the feature; guarded so this module still imports before it is integrated.
    from app.domain.email_intake import EmailIntakeError, recent_messages, test_connection
except ImportError:  # pragma: no cover
    class EmailIntakeError(Exception):  # type: ignore[no-redef]
        code = "EMAIL_IMAP_ERROR"
        message = "De mailserver gaf een onverwachte fout. Probeer het over een paar minuten opnieuw."

    def recent_messages(session, limit=10):  # type: ignore[no-redef]
        return []

    def test_connection(settings):  # type: ignore[no-redef]
        raise EmailIntakeError()

router = APIRouter(include_in_schema=False)

NOT_CONFIGURED_MESSAGE = (
    "De mailbox is nog niet gekoppeld. Vul IMAP_HOST, IMAP_USER en IMAP_PASSWORD "
    "in je .env-bestand in en start het programma opnieuw."
)
RECENT_LIMIT = 10


def email_settings(request: Request) -> dict:
    """Read-only view of the IMAP settings. The password is never included, only whether it is set."""
    s = request.app.state.settings
    return {
        "configured": bool(getattr(s, "imap_configured", False)),
        "host": getattr(s, "imap_host", None),
        "port": getattr(s, "imap_port", 993),
        "user": getattr(s, "imap_user", None),
        "password_set": getattr(s, "imap_password", None) is not None,
        "folder": getattr(s, "imap_folder", "INBOX"),
        "processed_folder": getattr(s, "imap_processed_folder", "Verwerkt"),
        "interval": getattr(s, "imap_poll_interval_minutes", 0) or 0,
    }


def _settings_page(request: Request, session: Session, connection=None) -> HTMLResponse:
    runner = getattr(request.app.state, "email_runner", None)
    return web.templates.TemplateResponse(
        request,
        "email/settings.html",
        web.page_context(
            request,
            title="Je factuurmailbox",
            cfg=email_settings(request),
            messages=list(recent_messages(session, RECENT_LIMIT)),
            last_report=getattr(runner, "last_report", None),
            connection=connection,
        ),
    )


@router.post("/inbox/ophalen")
def inbox_fetch(request: Request):
    state = request.app.state
    if not email_settings(request)["configured"]:
        state.email_flash_error = {"code": "EMAIL_NOT_CONFIGURED", "message": NOT_CONFIGURED_MESSAGE}
        return RedirectResponse("/inbox?melding=fout", status_code=303)
    try:
        result = state.email_runner.run_now()
    except EmailIntakeError as exc:
        state.email_flash_error = {"code": exc.code, "message": exc.message}
        return RedirectResponse("/inbox?melding=fout", status_code=303)
    if getattr(result, "status", None) == "bezig":
        return RedirectResponse("/inbox?melding=bezig", status_code=303)
    return RedirectResponse("/inbox?melding=opgehaald", status_code=303)


@router.get("/instellingen/email")
def email_settings_page(request: Request, session: Session = Depends(get_session)):
    return _settings_page(request, session)


@router.post("/instellingen/email/test")
def email_connection_test(request: Request, session: Session = Depends(get_session)):
    try:
        result = test_connection(request.app.state.settings)
    except EmailIntakeError as exc:
        return _settings_page(request, session, connection={"ok": False, "message": exc.message})
    return _settings_page(
        request, session,
        connection={"ok": True, "unread_count": result.unread_count, "folder": result.folder},
    )
