"""Filing (indienen) of a btw-aangifte and locking of its periods.

Filing never sends anything to the Belastingdienst: the user files in the portal and then
marks the aangifte as ingediend here. That stores a frozen snapshot (JSON with only ints and
strings) and locks the monthly periods it covers. Everything flushes, nothing commits; the
whole operation runs in a savepoint so a failure leaves no half-locked periods.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Sequence

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
    round_final_cents,
    round_whole_cents,
)
from app.domain.vat.settlement import settle_vat_period
from app.domain.vat.supplement import Supplement, compare_with_filed, mark_included, pick_supplements
from app.domain.vat.settings import get_vat_settings, is_kor
from app.models import CompanyProfile, FiscalYear, Period, VatReturn

SNAPSHOT_VERSION = 1


@dataclass(frozen=True)
class SupplementRef:
    """A suppletie taken along in an aangifte: what it corrects and by how much."""

    id: int
    label: str  # the corrected period, e.g. 'Q3 2026'
    total_cents: int


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
    supplements: list[SupplementRef] = field(default_factory=list)


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
    differs: bool = False  # ingediend, but the books changed since
    open_supplement: bool = False

    @property
    def rounded_cents(self) -> int | None:
        """Whole-euro amount to file (signed like total_cents), None when not started."""
        return None if self.total_cents is None else round_final_cents(self.total_cents)


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
        "supplements": [{"id": r.id, "label": r.label, "total_cents": r.total_cents} for r in s.supplements],
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
        totals=_with_rounded(dict(d["totals"])),
        icp=[IcpRow(**{**r, "entry_ids": tuple(r["entry_ids"])}) for r in d["icp"]],
        icp_unassigned=[
            IcpUnassigned(**{**u, "booking_date": date.fromisoformat(u["booking_date"])})
            for u in d["icp_unassigned"]
        ],
        warnings=[VatWarning(w["code"], w["message"], tuple(w["entry_ids"])) for w in d["warnings"]],
        filed_on=date.fromisoformat(d["filed_on"]) if d["filed_on"] else None,
        reference=d["reference"],
        is_concept=d["is_concept"],
        supplements=[SupplementRef(**r) for r in d.get("supplements", [])],
    )


def _with_rounded(totals: dict[str, int]) -> dict[str, int]:
    """Snapshots filed before the whole-euro rule lack '5g_afgerond': derive it from the exact total."""
    totals.setdefault("5g_afgerond", round_final_cents(totals["5g"]))
    return totals


def _merge_supplements(lines: list[RubriekLine], totals: dict[str, int], supplements: list[Supplement]):
    """Add the differences of the taken-along suppleties to the rubriek lines and totals."""
    grondslag: dict[str, int] = {}
    vat: dict[str, int] = {}
    for s in supplements:
        for l in s.lines:
            grondslag[l.rubriek] = grondslag.get(l.rubriek, 0) + l.grondslag_cents
            vat[l.rubriek] = vat.get(l.rubriek, 0) + l.vat_cents
    merged = [
        RubriekLine(l.rubriek, l.side, l.label, l.grondslag_cents + grondslag.get(l.rubriek, 0),
                    round_whole_cents(l.grondslag_cents + grondslag.get(l.rubriek, 0)),
                    l.vat_cents + vat.get(l.rubriek, 0))
        for l in lines
    ]
    five_a = totals["5a"] + sum(s.totals["5a"] for s in supplements)
    five_b = totals["5b"] + sum(s.totals["5b"] for s in supplements)
    new_totals = {"5a": five_a, "5b": five_b, "5c": five_a - five_b, "5g": five_a - five_b,
                  "5g_afgerond": round_final_cents(five_a - five_b)}
    return merged, new_totals


def _live_snapshot(
    session: Session, period: VatPeriod, *, status: str, filed_on: date | None, reference: str | None,
    supplements: list[Supplement] | None = None,
) -> ReturnSnapshot:
    start, end = period_range(period)
    report = build_vat_report(session, start, end)
    icp = build_icp(session, start, end)
    company = session.get(CompanyProfile, 1)
    supplements = supplements or []
    lines, totals = _merge_supplements(report.lines, dict(report.totals), supplements)
    return ReturnSnapshot(
        period=period,
        status=status,
        company_name=company.legal_name if company else "",
        btw_id=company.btw_id if company else None,
        lines=lines,
        totals=totals,
        icp=icp.rows,
        icp_unassigned=icp.unassigned,
        warnings=[*report.warnings, *icp.warnings],
        filed_on=filed_on,
        reference=reference,
        is_concept=status == "concept",
        supplements=[SupplementRef(s.id, s.period.label, s.total_cents) for s in supplements],
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


def get_snapshot(
    session: Session, period: VatPeriod, *, today: date | None = None, supplement_ids: Sequence[int] = (),
) -> ReturnSnapshot:
    """The stored snapshot of an ingediende aangifte, otherwise a live concept.

    A concept takes along the suppleties in `supplement_ids` (VAT_SUPPLEMENT_INVALID if one cannot be)."""
    filed = get_return(session, period)
    if filed is not None:
        return filed.snapshot
    picked = pick_supplements(session, period, supplement_ids)
    return _live_snapshot(session, period, status="concept", filed_on=None, reference=None, supplements=picked)


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
            comparison = compare_with_filed(session, p)
            rows.append(ReturnRow(p, "ingediend", deadline(p), False, r.total_cents, _direction(r.total_cents),
                                  kor, r.filed_on, comparison.differs, comparison.open_supplement is not None))
        elif has_entries(session, start, end):
            total = build_vat_report(session, start, end).totals["5g"]
            rows.append(ReturnRow(p, "concept", deadline(p), is_overdue(p, today), total, _direction(total), kor))
        else:
            rows.append(ReturnRow(p, "niet_gestart", deadline(p), is_overdue(p, today), None, None, kor))
    return rows


# --- filing ---------------------------------------------------------------------------


def file_vat_return(
    session: Session, vat_period: VatPeriod, *, filed_on: date, reference: str | None = None,
    today: date | None = None, supplement_ids: Sequence[int] = (),
) -> FiledReturn:
    """Mark a period's aangifte as ingediend: freeze the snapshot and lock its months.

    `supplement_ids` takes suppleties of earlier periods along; their btw is settled with this period."""
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

    picked = pick_supplements(session, vat_period, supplement_ids)
    with session.begin_nested():
        snapshot = _live_snapshot(
            session, vat_period, status="ingediend", filed_on=filed_on, reference=reference, supplements=picked)
        row = VatReturn(
            year=vat_period.year, kind=vat_period.kind, number=vat_period.number,
            start_date=start, end_date=end, status="ingediend", filed_on=filed_on,
            filed_at=datetime.now(timezone.utc).replace(tzinfo=None), reference=reference or None,
            snapshot_json=snapshot_to_json(snapshot), total_cents=snapshot.totals["5g"],
        )
        session.add(row)
        session.flush()
        extra: dict[str, int] = {}
        for s in picked:
            for code, cents in s.settle.items():
                extra[code] = extra.get(code, 0) + cents
        settle_vat_period(session, vat_period, extra=extra, return_id=row.id)
        mark_included(session, picked, row.id)
        for m in months(vat_period):
            lock_period(session, month_periods[m].id)
    return _to_filed(row)
