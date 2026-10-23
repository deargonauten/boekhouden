"""Routes for /controle*: the "Klopt dit?" checklist before filing a BTW-aangifte.

Read-only. The checks live in app.domain.checks; this module only parses the period and renders.
"""

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import web
from app.db import get_session
from app.domain import checks, vat
from app.domain.errors import VAT_MESSAGES, LedgerError

router = APIRouter(include_in_schema=False)

LEVEL_LABELS = {"ok": "Klopt", "let_op": "Let op", "fout": "Fout"}
LEVEL_TONES = {"ok": "success", "let_op": "warning", "fout": "danger"}
LEVEL_ORDER = {"fout": 0, "let_op": 1, "ok": 2}


def _parse_period(year: str, kind: str, number: str) -> vat.VatPeriod:
    try:
        return vat.VatPeriod(int(year), kind, int(number))
    except ValueError:
        raise LedgerError("VAT_PERIOD_INVALID", VAT_MESSAGES["VAT_PERIOD_INVALID"])


def _path(period: vat.VatPeriod) -> str:
    return f"/controle/{period.year}/{period.kind}/{period.number}"


def _neighbour(period: vat.VatPeriod, step: int) -> vat.VatPeriod | None:
    """The period before (-1) or after (+1), crossing the year boundary; None when out of range."""
    count = 4 if period.kind == "quarter" else 12
    number, year = period.number + step, period.year
    if number < 1:
        year, number = year - 1, count
    elif number > count:
        year, number = year + 1, 1
    try:
        return vat.VatPeriod(year, period.kind, number)
    except ValueError:
        return None


@router.get("/controle")
def controle_current(session: Session = Depends(get_session)):
    today = date.today()
    period = vat.period_for_date(today, vat.kind_for_year(session, today.year))
    return RedirectResponse(_path(period), status_code=303)


@router.get("/controle/{year}/{kind}/{number}")
def controle_page(request: Request, year: str, kind: str, number: str, session: Session = Depends(get_session)):
    try:
        period = _parse_period(year, kind, number)
    except LedgerError:
        return web.not_found_response(request)
    report = checks.run_checks(session, period)
    ordered = sorted(report.checks, key=lambda c: LEVEL_ORDER[c.level])
    prev, nxt = _neighbour(period, -1), _neighbour(period, 1)
    return web.templates.TemplateResponse(
        request, "controle/index.html",
        web.page_context(
            request, title=f"Controle {period.label}", period=period, report=report, checks=ordered,
            level_labels=LEVEL_LABELS, level_tones=LEVEL_TONES,
            btw_href=f"/btw/{period.year}/{period.kind}/{period.number}",
            prev_href=_path(prev) if prev else None, next_href=_path(nxt) if nxt else None,
            prev_label=prev.label if prev else None, next_label=nxt.label if nxt else None,
        ),
    )
