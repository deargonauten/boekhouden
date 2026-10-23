"""Routes for /btw* and /instellingen/btw-aangifte. Parse input, call app.domain.vat, render.

No btw logic lives here; see app.domain.vat. Downloads (pdf/csv) live in btw_export_routes.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain import checks, ledger, vat
from app.domain.errors import VAT_MESSAGES, LedgerError
from app.domain.relations.service import list_contacts
from app.domain.vat.periods import is_overdue

router = APIRouter(include_in_schema=False)

NOT_FOUND_CODES = {"VAT_PERIOD_INVALID", "VAT_ENTRY_NOT_FOUND", "VAT_CONTACT_NOT_FOUND"}
CONFLICT_CODES = {
    "VAT_ALREADY_FILED", "VAT_EARLIER_NOT_FILED", "VAT_KOR_NO_RETURN", "VAT_ENTRY_LOCKED",
    "VAT_FREQUENCY_CONFLICT", "VAT_KOR_FILED", "PERIOD_LOCKED",
}
KIND_LABELS = {"quarter": "Per kwartaal", "month": "Per maand"}
STATUS_LABELS = {"niet_gestart": "Nog niet gestart", "concept": "Concept", "ingediend": "Ingediend"}
STATUS_TONES = {"niet_gestart": "neutral", "concept": "warning", "ingediend": "success"}
DIRECTION_TONES = {"pay": "warning", "refund": "info", "zero": "neutral"}


def _status_for(error: LedgerError) -> int:
    if error.code in NOT_FOUND_CODES:
        return 404
    return 409 if error.code in CONFLICT_CODES else 422


def _parse_period(year: str, kind: str, number: str) -> vat.VatPeriod:
    """Raises VAT_PERIOD_INVALID (404) for anything that is not a real period."""
    try:
        return vat.VatPeriod(int(year), kind, int(number))
    except ValueError:
        raise LedgerError("VAT_PERIOD_INVALID", VAT_MESSAGES["VAT_PERIOD_INVALID"])


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise LedgerError("VAT_DATE_INVALID", "Vul een geldige datum in, bijvoorbeeld 2026-07-01.")


logger = logging.getLogger(__name__)


def _path(period: vat.VatPeriod) -> str:
    return f"/btw/{period.year}/{period.kind}/{period.number}"


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    return web.templates.TemplateResponse(
        request, template, web.page_context(request, path_of=_path, **ctx), status_code=status
    )


def _period_or_404(request: Request, year: str, kind: str, number: str):
    try:
        return _parse_period(year, kind, number), None
    except LedgerError:
        return None, web.not_found_response(request)


# --- overview ---------------------------------------------------------------------------


@router.get("/btw")
def btw_overview(request: Request, jaar: str = "", session: Session = Depends(get_session)):
    today = date.today()
    try:
        year = int(jaar) if jaar else today.year
        if not 1900 <= year <= 9999:
            raise ValueError
    except ValueError:
        return web.not_found_response(request)
    kind = vat.kind_for_year(session, year)
    years = sorted({fy.year for fy in ledger.list_fiscal_years(session)} | {today.year, year}, reverse=True)
    return _render(
        request, "btw/index.html",
        title="BTW",
        year=year, years=years, kind=kind, kind_label=KIND_LABELS[kind],
        rows=vat.list_returns(session, year, kind, today=today),
        current=vat.period_for_date(today, kind) if today.year == year else None,
        settings=vat.get_vat_settings(session),
        omzet_cents=vat.year_omzet_cents(session, year),
        kor_limit_cents=vat.KOR_LIMIT_CENTS,
        status_labels=STATUS_LABELS, status_tones=STATUS_TONES, direction_tones=DIRECTION_TONES,
        direction_labels=vat.DIRECTION_LABELS,
    )


# --- aangifte page ----------------------------------------------------------------------


def _icp_context(session: Session, snapshot, locked: bool) -> dict:
    suggestions: dict[int, object] = {}
    customers: list = []
    if not locked and snapshot.icp_unassigned:
        customers = list_contacts(session, role="customer")
        for u in snapshot.icp_unassigned:
            found = vat.suggest_contact(session, u.entry_id)
            if found is not None:
                suggestions[u.entry_id] = found
    return {"snapshot": snapshot, "icp_locked": locked, "customers": customers, "suggestions": suggestions}


def _controle_report(session: Session, period: vat.VatPeriod):
    """The advisory check report for the banner; None (banner omitted) if the checks fail."""
    try:
        return checks.run_checks(session, period)
    except Exception:
        logger.exception("Controle voor aangifte failed for %s; banner omitted", period.label)
        return None


def _return_page(request: Request, session: Session, period: vat.VatPeriod, *, error=None, status=200):
    snapshot = vat.get_snapshot(session, period)
    filed = snapshot.status == "ingediend"
    total = snapshot.totals["5g"]
    direction = "pay" if total > 0 else "refund" if total < 0 else "zero"
    return _render(
        request, "btw/return.html", status,
        title=f"BTW-aangifte {period.label}",
        period=period, filed=filed, error=error,
        kor=vat.is_kor(period, vat.get_vat_settings(session)),
        deadline=vat.deadline(period), overdue=(not filed) and is_overdue(period),
        direction=direction, direction_label=vat.DIRECTION_LABELS[direction],
        is_empty=not any(l.grondslag_cents or l.vat_cents for l in snapshot.lines) and not any(snapshot.totals.values()),
        kor_limit_cents=vat.KOR_LIMIT_CENTS,
        base=_path(period),
        controle=None if filed else _controle_report(session, period),
        **_icp_context(session, snapshot, filed),
    )


@router.get("/btw/{year}/{kind}/{number}")
def btw_return(request: Request, year: str, kind: str, number: str, session: Session = Depends(get_session)):
    period, missing = _period_or_404(request, year, kind, number)
    return missing or _return_page(request, session, period)


@router.get("/btw/{year}/{kind}/{number}/rubriek/{rubriek}")
def btw_drilldown(
    request: Request, year: str, kind: str, number: str, rubriek: str, session: Session = Depends(get_session)
):
    period, missing = _period_or_404(request, year, kind, number)
    if missing:
        return missing
    start, end = vat.period_range(period)
    report = vat.build_vat_report(session, start, end)
    line = next((l for l in report.lines if l.rubriek == rubriek), None)
    if line is None:
        return web.not_found_response(request)
    return _render(
        request, "btw/drilldown.html",
        title=f"{line.label} ({rubriek})", period=period, line=line,
        rows=vat.drilldown(session, start, end, rubriek), base=_path(period),
    )


# --- ICP coupling -----------------------------------------------------------------------


@router.post("/btw/{year}/{kind}/{number}/klant")
def btw_couple_klant(
    request: Request, year: str, kind: str, number: str,
    entry_id: int = Form(0), contact_id: int = Form(0), session: Session = Depends(get_session),
):
    period, missing = _period_or_404(request, year, kind, number)
    if missing:
        return missing
    error, status = None, 200
    try:
        vat.couple_entry_contact(session, entry_id, contact_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        error, status = exc.message, _status_for(exc)
    if request.headers.get("HX-Request") != "true":
        if error is None:
            return RedirectResponse(_path(period) + "#icp", status_code=303)
        return _return_page(request, session, period, error=error, status=status)
    snapshot = vat.get_snapshot(session, period)
    return _render(
        request, "btw/_icp.html", status,
        period=period, base=_path(period), icp_error=error,
        **_icp_context(session, snapshot, snapshot.status == "ingediend"),
    )


# --- indienen ---------------------------------------------------------------------------


def _confirm_page(request, session, period, *, error=None, status=200, values=None):
    return _render(
        request, "btw/confirm.html", status,
        title=f"Aangifte {period.label} indienen", period=period, base=_path(period),
        month_count=len(vat.months(period)), closes_year=max(vat.months(period)) == 12, error=error,
        values=values or {"filed_on": date.today().isoformat(), "reference": ""},
        snapshot=vat.get_snapshot(session, period),
        kor=vat.is_kor(period, vat.get_vat_settings(session)),
        controle=_controle_report(session, period),
    )


@router.get("/btw/{year}/{kind}/{number}/indienen")
def btw_confirm(request: Request, year: str, kind: str, number: str, session: Session = Depends(get_session)):
    period, missing = _period_or_404(request, year, kind, number)
    if missing:
        return missing
    if vat.get_return(session, period) is not None:
        return _return_page(request, session, period, error=VAT_MESSAGES["VAT_ALREADY_FILED"], status=409)
    return _confirm_page(request, session, period)


@router.post("/btw/{year}/{kind}/{number}/indienen")
def btw_file(
    request: Request, year: str, kind: str, number: str,
    filed_on: str = Form(""), reference: str = Form(""), session: Session = Depends(get_session),
):
    period, missing = _period_or_404(request, year, kind, number)
    if missing:
        return missing
    values = {"filed_on": filed_on, "reference": reference}
    try:
        day = _parse_date(filed_on) or date.today()
        vat.file_vat_return(session, period, filed_on=day, reference=reference.strip() or None)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _confirm_page(request, session, period, error=exc.message, status=_status_for(exc), values=values)
    return RedirectResponse(_path(period), status_code=303)


# --- settings ---------------------------------------------------------------------------


def _settings_page(request: Request, session: Session, *, error=None, status=200, values=None, saved=False):
    current = vat.get_vat_settings(session)
    year = date.today().year
    return _render(
        request, "btw/settings.html", status,
        title="BTW-aangifte", error=error, saved=saved,
        values=values or {
            "frequency": current.frequency,
            "kor_from": current.kor_from.isoformat() if current.kor_from else "",
            "kor_until": current.kor_until.isoformat() if current.kor_until else "",
        },
        year=year, omzet_cents=vat.year_omzet_cents(session, year), kor_limit_cents=vat.KOR_LIMIT_CENTS,
        frequencies=KIND_LABELS,
    )


@router.get("/instellingen/btw-aangifte")
def btw_settings(request: Request, opgeslagen: str = "", session: Session = Depends(get_session)):
    return _settings_page(request, session, saved=bool(opgeslagen))


@router.post("/instellingen/btw-aangifte")
def btw_settings_save(
    request: Request, frequency: str = Form("quarter"), kor_from: str = Form(""), kor_until: str = Form(""),
    session: Session = Depends(get_session),
):
    values = {"frequency": frequency, "kor_from": kor_from, "kor_until": kor_until}
    try:
        vat.save_vat_settings(session, frequency, _parse_date(kor_from), _parse_date(kor_until))
        session.commit()
    except LedgerError as exc:
        session.rollback()
        return _settings_page(request, session, error=exc.message, status=_status_for(exc), values=values)
    return RedirectResponse("/instellingen/btw-aangifte?opgeslagen=1", status_code=303)
