"""Suppletie: wat er sinds het indienen is veranderd in een ingediende periode, om mee te nemen in een latere aangifte.

The filed snapshot never changes. A supplement freezes the difference per rubriek between that
snapshot (plus supplements already taken along) and the books as they are today. Taking it along
in a later aangifte adds the difference to that aangifte (see filing.py); the btw sitting on the
btw accounts of the earlier period is then settled together with the later period.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.errors import vat_error
from app.domain.vat.periods import VatPeriod, period_range
from app.domain.vat.report import RubriekLine, build_vat_report
from app.domain.vat.settlement import SETTLED_CODES, net_movement
from app.models import Account, VatReturn, VatSupplement

SUPPLEMENT_VERSION = 1


@dataclass(frozen=True)
class SupplementLine:
    """The difference of one rubriek; amounts are filed-after minus filed-before, unrounded."""

    rubriek: str
    side: str
    label: str
    grondslag_cents: int
    vat_cents: int


@dataclass(frozen=True)
class Supplement:
    id: int
    period: VatPeriod  # the filed period it corrects
    created_at: datetime
    lines: list[SupplementLine]
    totals: dict[str, int]  # difference of '5a', '5b', '5g'
    settle: dict[str, int]  # btw account code -> debit minus credit still to settle
    included_in: VatPeriod | None

    @property
    def total_cents(self) -> int:
        return self.totals["5g"]


@dataclass(frozen=True)
class ComparisonRow:
    rubriek: str
    side: str
    label: str
    filed_grondslag_cents: int
    live_grondslag_cents: int
    filed_vat_cents: int
    live_vat_cents: int

    @property
    def grondslag_diff_cents(self) -> int:
        return self.live_grondslag_cents - self.filed_grondslag_cents

    @property
    def vat_diff_cents(self) -> int:
        return self.live_vat_cents - self.filed_vat_cents

    @property
    def differs(self) -> bool:
        return bool(self.grondslag_diff_cents or self.vat_diff_cents)


@dataclass(frozen=True)
class Comparison:
    period: VatPeriod
    rows: list[ComparisonRow]
    filed_cents: int  # 5g as filed, including suppleties already taken along
    live_cents: int  # 5g per today
    filed_5b_cents: int
    live_5b_cents: int
    open_supplement: Supplement | None

    @property
    def diff_cents(self) -> int:
        return self.live_cents - self.filed_cents

    @property
    def differs(self) -> bool:
        return any(r.differs for r in self.rows) or self.live_5b_cents != self.filed_5b_cents or bool(self.diff_cents)


# --- (de)serialization ---------------------------------------------------------------------


def _to_json(lines: list[SupplementLine], totals: dict[str, int], settle: dict[str, int]) -> str:
    return json.dumps({
        "v": SUPPLEMENT_VERSION,
        "lines": [vars(l) for l in lines],
        "totals": totals,
        "settle": settle,
    }, sort_keys=True, ensure_ascii=False)


def _to_supplement(row: VatSupplement) -> Supplement:
    d = json.loads(row.snapshot_json)
    included = None
    if row.included_in_return_id is not None:
        r = _return_by_id(row)
        included = VatPeriod(r.year, r.kind, r.number)
    return Supplement(
        row.id, VatPeriod(row.year, row.kind, row.number), row.created_at,
        [SupplementLine(**l) for l in d["lines"]], dict(d["totals"]), dict(d["settle"]), included,
    )


def _return_by_id(row: VatSupplement) -> VatReturn:
    from sqlalchemy.orm import object_session
    return object_session(row).get(VatReturn, row.included_in_return_id)


# --- reading --------------------------------------------------------------------------------


def _rows(session: Session, period: VatPeriod) -> list[VatSupplement]:
    return list(session.scalars(select(VatSupplement).where(
        VatSupplement.year == period.year, VatSupplement.kind == period.kind, VatSupplement.number == period.number,
    ).order_by(VatSupplement.id)))


def get_supplement(session: Session, supplement_id: int) -> Supplement | None:
    row = session.get(VatSupplement, supplement_id)
    return _to_supplement(row) if row else None


def supplements_of(session: Session, period: VatPeriod) -> list[Supplement]:
    """All suppleties of a filed period, oldest first."""
    return [_to_supplement(r) for r in _rows(session, period)]


def _taken_along_by(session: Session, period: VatPeriod) -> list[Supplement]:
    """Suppleties of earlier periods that the filed aangifte of `period` took along."""
    ret = session.scalar(select(VatReturn.id).where(
        VatReturn.year == period.year, VatReturn.kind == period.kind, VatReturn.number == period.number))
    if ret is None:
        return []
    return [_to_supplement(r) for r in session.scalars(
        select(VatSupplement).where(VatSupplement.included_in_return_id == ret).order_by(VatSupplement.id))]


def open_supplement(session: Session, period: VatPeriod) -> Supplement | None:
    return next((s for s in supplements_of(session, period) if s.included_in is None), None)


def available_supplements(session: Session, period: VatPeriod) -> list[Supplement]:
    """Suppleties that can still be taken along in the aangifte of `period`: not yet taken along, of an earlier period."""
    start, _ = period_range(period)
    return [
        _to_supplement(r) for r in session.scalars(
            select(VatSupplement).where(VatSupplement.included_in_return_id.is_(None), VatSupplement.end_date < start)
            .order_by(VatSupplement.id))
    ]


# --- difference ---------------------------------------------------------------------------


def _base(session: Session, period: VatPeriod):
    """Filed snapshot plus the suppleties already taken along: lines by rubriek and the 5b total."""
    from app.domain.vat.filing import get_return

    filed = get_return(session, period)
    if filed is None:
        raise vat_error("VAT_NOT_FILED")
    lines = {l.rubriek: [l.side, l.label, l.grondslag_cents, l.vat_cents] for l in filed.snapshot.lines}
    five_b = filed.snapshot.totals["5b"]
    # What this aangifte took along from earlier periods is not in this period's books: take it out again.
    for s in _taken_along_by(session, period):
        for l in s.lines:
            cur = lines[l.rubriek]
            cur[2] -= l.grondslag_cents
            cur[3] -= l.vat_cents
        five_b -= s.totals["5b"]
    for s in supplements_of(session, period):
        if s.included_in is None:
            continue
        for l in s.lines:
            cur = lines.setdefault(l.rubriek, [l.side, l.label, 0, 0])
            cur[2] += l.grondslag_cents
            cur[3] += l.vat_cents
        five_b += s.totals["5b"]
    return lines, five_b, filed


def compare_with_filed(session: Session, period: VatPeriod) -> Comparison:
    """Filed aangifte against the books today. Raises VAT_NOT_FILED for a period that is not filed."""
    base, base_5b, filed = _base(session, period)
    start, end = period_range(period)
    live = build_vat_report(session, start, end)
    rows = []
    for l in live.lines:
        side, label, g, v = base.get(l.rubriek, [l.side, l.label, 0, 0])
        rows.append(ComparisonRow(l.rubriek, l.side, l.label, g, l.grondslag_cents, v, l.vat_cents))
    base_5a = sum(r.filed_vat_cents for r in rows)
    return Comparison(
        period, rows, base_5a - base_5b, live.totals["5g"], base_5b, live.totals["5b"], open_supplement(session, period),
    )


# --- writing ------------------------------------------------------------------------------


def _leftover_by_account(session: Session, period: VatPeriod) -> dict[str, int]:
    """Btw still standing on the btw accounts in the period, after its own afrekening and earlier suppleties."""
    start, end = period_range(period)
    ids = dict(session.execute(select(Account.code, Account.id).where(Account.code.in_(SETTLED_CODES))).all())
    taken = {}
    for s in supplements_of(session, period):
        if s.included_in is not None:
            for code, v in s.settle.items():
                taken[code] = taken.get(code, 0) + v
    result = {}
    for code, account_id in ids.items():
        left = net_movement(session, account_id, start, end) - taken.get(code, 0)
        if left:
            result[code] = left
    return result


def create_supplement(session: Session, period: VatPeriod) -> Supplement:
    """Freeze today's difference with the filed aangifte of `period` as a suppletie."""
    _base(session, period)  # raises VAT_NOT_FILED
    if open_supplement(session, period) is not None:
        raise vat_error("VAT_SUPPLEMENT_EXISTS", periode=period.label)
    comparison = compare_with_filed(session, period)
    if not comparison.differs:
        raise vat_error("VAT_NO_DIFFERENCE")
    lines = [
        SupplementLine(r.rubriek, r.side, r.label, r.grondslag_diff_cents, r.vat_diff_cents)
        for r in comparison.rows if r.differs
    ]
    five_a = sum(l.vat_cents for l in lines)
    five_b = comparison.live_5b_cents - comparison.filed_5b_cents
    totals = {"5a": five_a, "5b": five_b, "5g": five_a - five_b}
    start, end = period_range(period)
    row = VatSupplement(
        year=period.year, kind=period.kind, number=period.number, start_date=start, end_date=end,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        snapshot_json=_to_json(lines, totals, _leftover_by_account(session, period)), total_cents=totals["5g"],
    )
    session.add(row)
    session.flush()
    return _to_supplement(row)


def delete_supplement(session: Session, supplement_id: int) -> None:
    """Remove a suppletie that is not taken along yet."""
    row = session.get(VatSupplement, supplement_id)
    if row is None:
        raise vat_error("VAT_SUPPLEMENT_NOT_FOUND")
    if row.included_in_return_id is not None:
        raise vat_error("VAT_SUPPLEMENT_INCLUDED")
    session.execute(delete(VatSupplement).where(VatSupplement.id == supplement_id))
    session.expire_all()


def pick_supplements(session: Session, period: VatPeriod, ids: Sequence[int]) -> list[Supplement]:
    """The suppleties to take along in `period`, validated; VAT_SUPPLEMENT_INVALID for any that cannot be."""
    allowed = {s.id: s for s in available_supplements(session, period)}
    picked = []
    for i in dict.fromkeys(ids):
        if i not in allowed:
            raise vat_error("VAT_SUPPLEMENT_INVALID")
        picked.append(allowed[i])
    return picked


def mark_included(session: Session, supplements: Sequence[Supplement], return_id: int) -> None:
    for s in supplements:
        row = session.get(VatSupplement, s.id)
        row.included_in_return_id = return_id
    session.flush()
