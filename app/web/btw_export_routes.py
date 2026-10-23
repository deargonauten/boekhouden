"""Download routes for the BTW-aangifte: PDF, rubrieken-CSV and ICP-CSV.

Parse the period, take the snapshot from app.domain.vat, hand it to app.domain.vat.export.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.errors import LedgerError
from app.domain.vat import VatPeriod, get_snapshot
from app.domain.vat import export

router = APIRouter(include_in_schema=False)

KIND_ALIASES = {"quarter": "quarter", "kwartaal": "quarter", "month": "month", "maand": "month"}
NOT_FOUND = "Deze periode bestaat niet. Kies een kwartaal van 1 tot 4 of een maand van 1 tot 12."


def _period(year: str, kind: str, number: str) -> VatPeriod | None:
    if not (year.isascii() and year.isdigit() and number.isascii() and number.isdigit()):
        return None
    if kind not in KIND_ALIASES:
        return None
    try:
        return VatPeriod(int(year), KIND_ALIASES[kind], int(number))
    except LedgerError:
        return None


def _download(session: Session, year: str, kind: str, number: str, build, filename, media_type: str) -> Response:
    period = _period(year, kind, number)
    if period is None:
        return PlainTextResponse(NOT_FOUND, status_code=404)
    try:
        snapshot = get_snapshot(session, period)
    except LedgerError as error:
        return PlainTextResponse(error.message, status_code=409)
    return Response(
        build(snapshot),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename(period)}"'},
    )


@router.get("/btw/{year}/{kind}/{number}/pdf")
def download_pdf(year: str, kind: str, number: str, session: Session = Depends(get_session)):
    return _download(session, year, kind, number, export.aangifte_pdf, export.filename_pdf, "application/pdf")


@router.get("/btw/{year}/{kind}/{number}/rubrieken.csv")
def download_rubrieken_csv(year: str, kind: str, number: str, session: Session = Depends(get_session)):
    return _download(session, year, kind, number, export.rubrieken_csv, export.filename_rubrieken_csv,
                     "text/csv; charset=utf-8")


@router.get("/btw/{year}/{kind}/{number}/icp.csv")
def download_icp_csv(year: str, kind: str, number: str, session: Session = Depends(get_session)):
    return _download(session, year, kind, number, export.icp_csv, export.filename_icp_csv,
                     "text/csv; charset=utf-8")
