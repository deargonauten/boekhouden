"""Filing (indienen) of a btw-aangifte and locking of its periods.

Filing never sends anything to the Belastingdienst: the user files in the portal and then
marks the aangifte as ingediend here. That stores a frozen snapshot (JSON with only ints and
strings) and locks the monthly periods it covers. Everything flushes, nothing commits; the
whole operation runs in a savepoint so a failure leaves no half-locked periods.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import vat_error
from app.domain.ledger import lock_period
from app.domain.vat.icp import IcpRow, IcpUnassigned, build_icp
from app.domain.vat.periods import (
    VatPeriod,
    deadline,
    is_overdue,
    months,
    overlaps,
    period_range,
    periods_of_year,
)
from app.domain.vat.report import (
    DIRECTION_LABELS,
    PAY,
    REFUND,
    ZERO,
    RubriekLine,
    VatWarning,
    build_vat_report,
    has_entries,
)
from app.domain.vat.settings import get_vat_settings, is_kor
from app.models import CompanyProfile, FiscalYear, Period, VatReturn

SNAPSHOT_VERSION = 1


@dataclass
class ReturnSnapshot:
    """Everything an export needs; live for a concept, stored JSON for an ingediende aangifte."""

    period: VatPeriod
    status: str  # 'concept' | 'ingediend'
    company_name: str
    btw_id: str | None
    lines: list[RubriekLine]
    totals: dict[str, int]  # '5a', '5b', '5c', '5g'
    icp: list[IcpRow]
    icp_unassigned: list[IcpUnassigned]
    warnings: list[VatWarning]
    filed_on: date | None
    reference: str | None
    is_concept: bool


@dataclass(frozen=True)
class ReturnRow:
    """One line of the overview page."""

    period: VatPeriod
    status: str  # 'niet_gestart' | 'concept' | 'ingediend'
    deadline: date
    overdue: bool
    total_cents: int | None
    direction: str | None  # 'pay' | 'refund' | 'zero' (see report.DIRECTION_LABELS)
    kor: str  # 'none' | 'partial' | 'full'
    filed_on: date | None = None


@dataclass(frozen=True)
class FiledReturn:
    period: VatPeriod
    filed_on: date
    filed_at: datetime
    reference: str | None
    total_cents: int
    snapshot: ReturnSnapshot


# --- snapshot (de)serialization ----------------------------------------------------


def snapshot_to_json(s: ReturnSnapshot) -> str:
    data = {
        "v": SNAPSHOT_VERSION,
        "period": {"year": s.period.year, "kind": s.period.kind, "number": s.period.number},
        "status": s.status,
        "company_name": s.company_name,
        "btw_id": s.btw_id,
        "lines": [
            {"rubriek": l.rubriek, "side": l.side, "label": l.label, "grondslag_cents": l.grondslag_cents,
             "grondslag_whole_cents": l.grondslag_whole_cents, "vat_cents": l.vat_cents}
            for l in s.lines
        ],
        "totals": dict(s.totals),
        "icp": [
            {"country": r.country, "btw_number": r.btw_number, "goederen_cents": r.goederen_cents,
             "diensten_cents": r.diensten_cents, "driehoek_cents": r.driehoek_cents,
             "contact_id": r.contact_id, "name": r.name, "issue": r.issue, "entry_ids": list(r.entry_ids)}
            for r in s.icp
        ],
        "icp_unassigned": [
            {"entry_id": u.entry_id, "entry_number": u.entry_number, "booking_date": u.booking_date.isoformat(),
             "description": u.description, "goederen_cents": u.goederen_cents, "diensten_cents": u.diensten_cents}
            for u in s.icp_unassigned
        ],
        "warnings": [{"code": w.code, "message": w.message, "entry_ids": list(w.entry_ids)} for w in s.warnings],
        "filed_on": s.filed_on.isoformat() if s.filed_on else None,
        "reference": s.reference,
        "is_concept": s.is_concept,
    }
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def snapshot_from_json(raw: str) -> ReturnSnapshot:
    d = json.loads(raw)
    p = d["period"]
    return ReturnSnapshot(
        period=VatPeriod(p["year"], p["kind"], p["number"]),
        status=d["status"],
        company_name=d["company_name"],
        btw_id=d["btw_id"],
        lines=[RubriekLine(**l) for l in d["lines"]],
        totals=dict(d["totals"]),
        icp=[IcpRow(**{**r, "entry_ids": tuple(r["entry_ids"])}) for r in d["icp"]],
        icp_unassigned=[
            IcpUnassigned(**{**u, "booking_date": date.fromisoformat(u["booking_date"])})
            for u in d["icp_unassigned"]
        ],
        warnings=[VatWarning(w["code"], w["message"], tuple(w["entry_ids"])) for w in d["warnings"]],
        filed_on=date.fromisoformat(d["filed_on"]) if d["filed_on"] else None,
        reference=d["reference"],
        is_concept=d["is_concept"],
    )


def _live_snapshot(
    session: Session, period: VatPeriod, *, status: str, filed_on: date | None, reference: str | None,
) -> ReturnSnapshot:
    start, end = period_range(period)
    report = build_vat_report(session, start, end)
    icp = build_icp(session, start, end)
    company = session.get(CompanyProfile, 1)
    return ReturnSnapshot(
        period=period,
        status=status,
        company_name=company.legal_name if company else "",
        btw_id=company.btw_id if company else None,
        lines=report.lines,
        totals=dict(report.totals),
        icp=icp.rows,
        icp_unassigned=icp.unassigned,
        warnings=[*report.warnings, *icp.warnings],
        filed_on=filed_on,
        reference=reference,
        is_concept=status == "concept",
    )


# --- reading --------------------------------------------------------------------------


def _direction(total: int) -> str:
    return PAY if total > 0 else REFUND if total < 0 else ZERO


def _filed_row(session: Session, period: VatPeriod) -> VatReturn | None:
    return session.scalar(select(VatReturn).where(
        VatReturn.year == period.year, VatReturn.kind == period.kind, VatReturn.number == period.number))


def _to_filed(row: VatReturn) -> FiledReturn:
    period = VatPeriod(row.year, row.kind, row.number)
    snap = snapshot_from_json(row.snapshot_json)
    snap.reference = row.reference  # may have been added after filing (the only allowed update)
    return FiledReturn(period, row.filed_on, row.filed_at, row.reference, row.total_cents, snap)


def get_return(session: Session, period: VatPeriod) -> FiledReturn | None:
    row = _filed_row(session, period)
    return _to_filed(row) if row else None


def get_snapshot(session: Session, period: VatPeriod, *, today: date | None = None) -> ReturnSnapshot:
    """The stored snapshot of an ingediende aangifte, otherwise a live concept."""
    filed = get_return(session, period)
    if filed is not None:
        return filed.snapshot
    return _live_snapshot(session, period, status="concept", filed_on=None, reference=None)


def kind_for_year(session: Session, year: int) -> str:
    """'quarter' or 'month' for a year: the kind already filed in it, otherwise the setting."""
    kind = session.scalar(select(VatReturn.kind).where(VatReturn.year == year).limit(1))
    return kind or get_vat_settings(session).frequency


def list_returns(session: Session, year: int, kind: str, *, today: date | None = None) -> list[ReturnRow]:
    today = today or date.today()
    settings = get_vat_settings(session)
    filed = {r.number: r for r in session.scalars(
        select(VatReturn).where(VatReturn.year == year, VatReturn.kind == kind))}
    rows: list[ReturnRow] = []
    for p in periods_of_year(year, kind):
        start, end = period_range(p)
        kor = is_kor(p, settings)
        if p.number in filed:
            r = filed[p.number]
            rows.append(ReturnRow(p, "ingediend", deadline(p), False, r.total_cents, _direction(r.total_cents),
                                  kor, r.filed_on))
        elif has_entries(session, start, end):
            total = build_vat_report(session, start, end).totals["5g"]
            rows.append(ReturnRow(p, "concept", deadline(p), is_overdue(p, today), total, _direction(total), kor))
        else:
            rows.append(ReturnRow(p, "niet_gestart", deadline(p), is_overdue(p, today), None, None, kor))
    return rows


# --- filing ---------------------------------------------------------------------------


def file_vat_return(
    session: Session, vat_period: VatPeriod, *, filed_on: date, reference: str | None = None,
    today: date | None = None,
) -> FiledReturn:
    """Mark a period's aangifte as ingediend: freeze the snapshot and lock its months."""
    today = today or date.today()
    start, end = period_range(vat_period)

    if _filed_row(session, vat_period) is not None:
        raise vat_error("VAT_ALREADY_FILED")
    year_returns = list(session.scalars(select(VatReturn).where(VatReturn.year == vat_period.year)))
    if any(overlaps(vat_period, VatPeriod(r.year, r.kind, r.number)) for r in year_returns):
        raise vat_error("VAT_ALREADY_FILED")
    if any(r.kind != vat_period.kind for r in year_returns):
        raise vat_error("VAT_FREQUENCY_CONFLICT", year=vat_period.year)
    if filed_on > today:
        raise vat_error("VAT_FUTURE_DATE")
    if is_kor(vat_period, get_vat_settings(session)) == "full":
        raise vat_error("VAT_KOR_NO_RETURN")

    company = session.get(CompanyProfile, 1)
    if company is None or not company.btw_id:
        raise vat_error("VAT_COMPANY_INCOMPLETE")

    fy = session.scalar(select(FiscalYear).where(FiscalYear.year == vat_period.year))
    month_periods = {}
    if fy is not None:
        month_periods = {p.number: p for p in session.scalars(select(Period).where(Period.fiscal_year_id == fy.id))}
    if any(m not in month_periods for m in months(vat_period)):
        raise vat_error("VAT_PERIOD_MISSING", year=vat_period.year)

    settings = get_vat_settings(session)
    for earlier in periods_of_year(vat_period.year, vat_period.kind)[: vat_period.number - 1]:
        e_start, e_end = period_range(earlier)
        if any(r.start_date <= e_start and e_end <= r.end_date for r in year_returns):
            continue
        if is_kor(earlier, settings) == "full" or not has_entries(session, e_start, e_end):
            continue
        raise vat_error("VAT_EARLIER_NOT_FILED", periode=earlier.label)

    with session.begin_nested():
        snapshot = _live_snapshot(session, vat_period, status="ingediend", filed_on=filed_on, reference=reference)
        row = VatReturn(
            year=vat_period.year, kind=vat_period.kind, number=vat_period.number,
            start_date=start, end_date=end, status="ingediend", filed_on=filed_on,
            filed_at=datetime.now(timezone.utc).replace(tzinfo=None), reference=reference or None,
            snapshot_json=snapshot_to_json(snapshot), total_cents=snapshot.totals["5g"],
        )
        session.add(row)
        session.flush()
        for m in months(vat_period):
            lock_period(session, month_periods[m].id)
    return _to_filed(row)
