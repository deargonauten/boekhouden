"""BTW-aangifte report: grondslag and btw per rubriek from the booked journal lines.

Factuurstelsel: everything is reported by the `booking_date` of the entry; opening entries
(`kind='opening'`) carry balances, not transactions, and are excluded.

Grondslag comes from the lines that carry a vat code (the net omzet/kosten line); the btw
amount comes from the btw accounts (so it equals what is printed on the invoice). The
aggregation (`aggregate`) is pure and works on `LineRow`s; `build_vat_report` adds the
checks that need the database (klant for ICP, earlier periods, KOR).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.vat.rubrieken import ALSO_INPUT_VAT, PURCHASE_RUBRIEKEN, SALES_RUBRIEKEN
from app.models import Account, JournalEntry, JournalLine, VatCode

# Account-to-rubriek mapping, by account code (not id).
BTW_ACCOUNT_RUBRIEK: dict[str, str] = {"3100": "1a", "3110": "1b", "3120": "1c", "3140": "1d"}
VERLEGD_PAYABLE = "3130"
INPUT_ACCOUNTS: tuple[str, ...] = ("1400", "1410")
_SALES_FAMILY = ("3100", "3110", "3120")  # btw on regular sales, compared with the rate (W3)
_VOORBELASTING = "1400"
_ALL_BTW_ACCOUNTS = (*BTW_ACCOUNT_RUBRIEK, VERLEGD_PAYABLE, *INPUT_ACCOUNTS)

# Rubrieken in the order of the Belastingdienst form, with their side.
RUBRIEK_ORDER: tuple[tuple[str, str], ...] = (
    ("1a", "sales"), ("1b", "sales"), ("1c", "sales"), ("1d", "sales"), ("1e", "sales"),
    ("2a", "purchase"), ("3a", "sales"), ("3b", "sales"), ("3c", "sales"),
    ("4a", "purchase"), ("4b", "purchase"),
)
_VERLEGD_RUBRIEKEN = tuple(r for r, _ in RUBRIEK_ORDER if r in ALSO_INPUT_VAT)  # 2a, 4a, 4b
TOTAL_LABELS: dict[str, str] = {
    "5a": "Verschuldigde btw",
    "5b": PURCHASE_RUBRIEKEN["5b"],
    "5c": "Subtotaal (verschuldigd min voorbelasting)",
    "5g": "Totaal",
    "5g_afgerond": "Afgerond bedrag voor je aangifte",
}
DIRECTION_LABELS: dict[str, str] = {
    "pay": "Te betalen", "refund": "Terug te vragen", "zero": "Niets te betalen",
}
EMPTY_MESSAGE = "Geen btw in deze periode"
TOLERANCE_CENTS = 5  # allowed rounding difference per entry between btw amount and grondslag * rate

# direction values of a report
PAY, REFUND, ZERO = "pay", "refund", "zero"


@dataclass(frozen=True)
class RubriekLine:
    rubriek: str
    side: str  # 'sales' | 'purchase'
    label: str
    grondslag_cents: int  # unrounded, for drill-down
    grondslag_whole_cents: int  # rounded toward zero to whole euros, for display/export
    vat_cents: int


@dataclass(frozen=True)
class VatWarning:
    code: str
    message: str
    entry_ids: tuple[int, ...] = ()


@dataclass
class VatReport:
    period_start: date
    period_end: date
    lines: list[RubriekLine]
    totals: dict[str, int]  # '5a', '5b', '5c', '5g' (exact cents), '5g_afgerond' (whole euros to file)
    warnings: list[VatWarning] = field(default_factory=list)
    direction: str = ZERO

    @property
    def is_empty(self) -> bool:
        return not any(l.grondslag_cents or l.vat_cents for l in self.lines) and not any(self.totals.values())

    @property
    def message(self) -> str | None:
        return EMPTY_MESSAGE if self.is_empty else None

    @property
    def direction_label(self) -> str:
        return DIRECTION_LABELS[self.direction]


@dataclass(frozen=True)
class LineRow:
    """One journal line with the entry, account and vat code facts the aggregation needs."""

    entry_id: int
    entry_number: str
    booking_date: date
    description: str
    line_id: int
    account_code: str
    account_name: str
    account_type: str
    debit_cents: int
    credit_cents: int
    vat_code: str | None = None
    rate_bp: int = 0
    sales_rubriek: str | None = None
    purchase_rubriek: str | None = None
    vat_active: bool = True


@dataclass(frozen=True)
class DrillLine:
    """A line behind a rubriek. `amount_cents` has the rubriek's sign (sales credit-debit, purchase debit-credit)."""

    entry_id: int
    entry_number: str
    booking_date: date
    description: str
    account_code: str
    account_name: str
    kind: str  # 'grondslag' | 'btw'
    amount_cents: int
    line_id: int


def round_whole_cents(cents: int) -> int:
    """Round toward zero to whole euros, never -0.

    Business rule: the omzet fields of the aangifte are whole euros, rounded down (toward
    zero); the individual btw rubriek amounts keep their cents. The final amount (5g) has its
    own rule, see `round_final_cents`.
    """
    whole = abs(cents) // 100 * 100
    return -whole if cents < 0 and whole else whole


def round_final_cents(cents: int) -> int:
    """Whole euros for the final amount of the aangifte (after 5a-5b), never -0.

    Business rule: an amount to pay (positive) is rounded down, an amount to be refunded
    (negative) is rounded up in absolute value, i.e. in the taxpayer's favour:
    12,99 betalen -> 12,00; 0,96 terug -> 1,00 terug. The exact cents stay in totals['5g'].
    """
    if cents >= 0:
        return cents // 100 * 100
    return -((-cents + 99) // 100 * 100)


def final_rounded(totals: dict[str, int]) -> int:
    """The rounded final amount of a totals dict; derived for snapshots stored before it existed."""
    return totals["5g_afgerond"] if "5g_afgerond" in totals else round_final_cents(totals["5g"])


def _div_round(numerator: int, denominator: int) -> int:
    """Integer division rounded half away from zero."""
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 2 + denominator) // (denominator * 2))


# --- classification -----------------------------------------------------------------


def _classify(row: LineRow) -> tuple[str, str] | str | None:
    """('sales'|'purchase', rubriek) for a grondslag line, 'ambiguous', or None (not part of the aangifte)."""
    if not row.vat_code:
        return None
    if row.sales_rubriek and row.account_type == "revenue":
        return "sales", row.sales_rubriek
    if row.purchase_rubriek and row.account_type in ("expense", "asset"):
        return "purchase", row.purchase_rubriek
    if row.sales_rubriek and row.purchase_rubriek and row.account_type not in ("revenue", "expense", "asset"):
        return "ambiguous"
    return None


@dataclass
class _Grondslag:
    row: LineRow
    side: str
    rubriek: str
    amount: int  # signed per side


@dataclass
class _EntryFacts:
    entry_id: int
    rows: list[LineRow] = field(default_factory=list)
    grondslag: list[_Grondslag] = field(default_factory=list)
    ambiguous: list[LineRow] = field(default_factory=list)
    net_credit: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # per btw account code
    verlegd_target: str | None = None
    verlegd_multi: bool = False


def _facts(rows: list[LineRow]) -> dict[int, _EntryFacts]:
    entries: dict[int, _EntryFacts] = {}
    for row in rows:
        f = entries.setdefault(row.entry_id, _EntryFacts(row.entry_id))
        f.rows.append(row)
        if row.account_code in _ALL_BTW_ACCOUNTS and not row.vat_code:
            f.net_credit[row.account_code] += row.credit_cents - row.debit_cents
        c = _classify(row)
        if c == "ambiguous":
            f.ambiguous.append(row)
        elif c is not None:
            side, rubriek = c
            amount = row.credit_cents - row.debit_cents if side == "sales" else row.debit_cents - row.credit_cents
            f.grondslag.append(_Grondslag(row, side, rubriek, amount))
    for f in entries.values():
        per: dict[str, int] = defaultdict(int)
        for g in f.grondslag:
            if g.side == "purchase" and g.rubriek in _VERLEGD_RUBRIEKEN:
                per[g.rubriek] += g.amount
        if per:
            f.verlegd_target = max(_VERLEGD_RUBRIEKEN, key=lambda r: (abs(per.get(r, 0)), -_VERLEGD_RUBRIEKEN.index(r)))
            f.verlegd_multi = len([r for r, v in per.items() if v]) > 1
    return entries


# --- pure aggregation ---------------------------------------------------------------


def aggregate(
    rows: list[LineRow], start: date, end: date,
    rubriek_catalogue: tuple[tuple[str, str], ...] = RUBRIEK_ORDER,
) -> VatReport:
    """Pure: line rows -> report (rubriek lines, totals and the warnings that need no database)."""
    facts = _facts(rows)
    grondslag: dict[str, int] = defaultdict(int)
    vat: dict[str, int] = defaultdict(int)
    voorbelasting = 0
    for f in facts.values():
        for g in f.grondslag:
            grondslag[g.rubriek] += g.amount
        for account, rubriek in BTW_ACCOUNT_RUBRIEK.items():
            vat[rubriek] += f.net_credit.get(account, 0)
        if f.verlegd_target:
            vat[f.verlegd_target] += f.net_credit.get(VERLEGD_PAYABLE, 0)
        voorbelasting -= sum(f.net_credit.get(a, 0) for a in INPUT_ACCOUNTS)

    labels = {"sales": SALES_RUBRIEKEN, "purchase": PURCHASE_RUBRIEKEN}
    lines = [
        RubriekLine(
            r, side, labels[side].get(r, r), grondslag[r], round_whole_cents(grondslag[r]), vat[r],
        )
        for r, side in rubriek_catalogue
    ]
    a5 = sum(l.vat_cents for l in lines)
    totals = {"5a": a5, "5b": voorbelasting, "5c": a5 - voorbelasting, "5g": a5 - voorbelasting,
              "5g_afgerond": round_final_cents(a5 - voorbelasting)}
    direction = PAY if totals["5g"] > 0 else REFUND if totals["5g"] < 0 else ZERO
    return VatReport(start, end, lines, totals, _warnings(facts), direction)


def _warnings(facts: dict[int, _EntryFacts]) -> list[VatWarning]:
    found: dict[str, set[int]] = defaultdict(set)
    for f in facts.values():
        _entry_warnings(f, found)
    return [
        VatWarning(code, _MESSAGES[code], tuple(sorted(ids)))
        for code in _WARNING_ORDER if (ids := found.get(code))
    ]


def _entry_warnings(f: _EntryFacts, found: dict[str, set[int]]) -> None:
    eid = f.entry_id
    btw_lines = [r for r in f.rows if r.account_code in _ALL_BTW_ACCOUNTS and not r.vat_code]
    has_rubriek_code = any(r.vat_code and (r.sales_rubriek or r.purchase_rubriek) for r in f.rows)
    if btw_lines and not has_rubriek_code:
        found["W2"].add(eid)
    if any(r.vat_code and not r.vat_active for r in f.rows):
        found["W7"].add(eid)
    if f.ambiguous:
        found["AMBIGUOUS_LINE"].add(eid)
    if f.verlegd_multi:
        found["W_MULTI_VERLEGD"].add(eid)

    # expected btw per family from the rate of the lines, compared with what is booked
    families = {
        "sales": ([g for g in f.grondslag if g.side == "sales" and g.rubriek in ("1a", "1b", "1c")],
                  _SALES_FAMILY, lambda a: f.net_credit.get(a, 0)),
        "verlegd": ([g for g in f.grondslag if g.side == "purchase" and g.rubriek in _VERLEGD_RUBRIEKEN],
                    (VERLEGD_PAYABLE,), lambda a: f.net_credit.get(a, 0)),
        "voorbelasting": ([g for g in f.grondslag if g.side == "purchase" and g.rubriek == "5b"],
                          (_VOORBELASTING,), lambda a: -f.net_credit.get(a, 0)),
    }
    for taxable_lines, accounts, actual_of in families.values():
        taxable = [g for g in taxable_lines if g.row.rate_bp > 0]
        if not taxable:
            continue
        if not any(r.account_code in accounts for r in btw_lines):
            found["W1"].add(eid)
            continue
        # compare per box: sales btw is checked per rubriek (1a/1b/1c) against its own account, so
        # a wrong 21% box cannot be hidden by a compensating error in the 9% box
        if accounts is _SALES_FAMILY:
            groups = [([g for g in taxable if g.rubriek == r], (a,)) for a, r in BTW_ACCOUNT_RUBRIEK.items()
                      if r in ("1a", "1b", "1c")]
        else:
            groups = [(taxable, accounts)]
        for group_lines, group_accounts in groups:
            expected = sum(_div_round(g.amount * g.row.rate_bp, 10000) for g in group_lines)
            if abs(sum(actual_of(a) for a in group_accounts) - expected) > TOLERANCE_CENTS:
                found["W3"].add(eid)

    if any(g.side == "purchase" and g.rubriek in _VERLEGD_RUBRIEKEN for g in f.grondslag):
        payable = f.net_credit.get(VERLEGD_PAYABLE, 0)
        deductible = -f.net_credit.get("1410", 0)
        if not payable or not deductible or payable != deductible:
            found["W5"].add(eid)


_WARNING_ORDER = ("W1", "W2", "W3", "W5", "W7", "W_MULTI_VERLEGD", "AMBIGUOUS_LINE")
_MESSAGES = {
    "W1": (
        "Er staat btw-grondslag zonder bijbehorende btw-boeking. Open deze boekingen en voeg de "
        "btw-regel toe, of kies de btw-code 'Geen btw' als er geen btw bij hoort."
    ),
    "W2": (
        "Er staat een btw-bedrag zonder omzet of kosten met een btw-code. Open deze boekingen en "
        "kies bij de omzet- of kostenregel de juiste btw-code."
    ),
    "W3": (
        "Het btw-bedrag past niet bij het btw-tarief (meer dan € 0,05 verschil). Controleer het "
        "bedrag of de btw-code in deze boekingen."
    ),
    "W5": (
        "Bij deze verlegde inkoop ontbreekt de btw-boeking, of de verschuldigde btw (3130) en de "
        "voorbelasting (1410) zijn niet even groot. Boek beide bedragen even groot."
    ),
    "W7": (
        "Deze boeking gebruikt een btw-code die niet meer in gebruik is. Controleer de rubriek van "
        "de code onder Instellingen > Btw-codes."
    ),
    "W_MULTI_VERLEGD": (
        "Deze boeking bevat meerdere verlegde soorten (verlegd, inkoop uit de EU, inkoop van buiten "
        "de EU). De btw is bij de grootste soort geteld. Splits de boeking als dat niet klopt."
    ),
    "AMBIGUOUS_LINE": (
        "Bij deze regel is niet duidelijk of het een verkoop of inkoop is, dus hij telt niet mee. "
        "Boek de regel op een omzet- of kostenrekening."
    ),
    "W4": (
        "Deze EU-verkoop heeft nog geen klant voor de ICP-opgaaf. Koppel een klant met btw-nummer "
        "in het ICP-overzicht."
    ),
}


def grondslag_lines(rows: list[LineRow], side: str, rubriek: str) -> list[tuple[LineRow, int]]:
    """(row, signed amount) of the grondslag lines on one side/rubriek, e.g. ('sales', '3b')."""
    return [
        (g.row, g.amount) for f in _facts(rows).values() for g in f.grondslag
        if g.side == side and g.rubriek == rubriek
    ]


# --- drill-down (pure) ----------------------------------------------------------------


def drilldown_rows(rows: list[LineRow], rubriek: str) -> list[DrillLine]:
    out: list[DrillLine] = []

    def add(r: LineRow, kind: str, amount: int) -> None:
        out.append(DrillLine(
            r.entry_id, r.entry_number, r.booking_date, r.description, r.account_code,
            r.account_name, kind, amount, r.line_id,
        ))

    for f in _facts(rows).values():
        for g in f.grondslag:
            if g.rubriek == rubriek and rubriek in {r for r, _ in RUBRIEK_ORDER}:
                add(g.row, "grondslag", g.amount)
        for r in f.rows:
            if r.vat_code or r.account_code not in _ALL_BTW_ACCOUNTS:
                continue
            credit_net = r.credit_cents - r.debit_cents
            if BTW_ACCOUNT_RUBRIEK.get(r.account_code) == rubriek:
                add(r, "btw", credit_net)
            elif r.account_code == VERLEGD_PAYABLE and f.verlegd_target == rubriek:
                add(r, "btw", credit_net)
            elif rubriek == "5b" and r.account_code in INPUT_ACCOUNTS:
                add(r, "btw", -credit_net)
    return out


# --- database -------------------------------------------------------------------------


def fetch_rows(session: Session, start: date, end: date) -> list[LineRow]:
    """One SQL pass: lines of non-opening entries in [start, end] with account and vat code."""
    q = (
        select(JournalLine, JournalEntry, Account, VatCode)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .outerjoin(VatCode, VatCode.code == JournalLine.vat_code)
        .where(JournalEntry.kind != "opening", JournalEntry.booking_date >= start, JournalEntry.booking_date <= end)
        .order_by(JournalEntry.id, JournalLine.line_no)
    )
    return [
        LineRow(
            e.id, e.entry_number, e.booking_date, e.description, l.id, a.code, a.name, a.type,
            l.debit_cents, l.credit_cents, l.vat_code,
            v.rate_bp if v else 0, v.sales_rubriek if v else None, v.purchase_rubriek if v else None,
            bool(v.is_active) if v else True,
        )
        for l, e, a, v in session.execute(q)
    ]


def has_entries(session: Session, start: date, end: date) -> bool:
    return session.scalar(
        select(JournalEntry.id)
        .where(JournalEntry.kind != "opening", JournalEntry.booking_date >= start, JournalEntry.booking_date <= end)
        .limit(1)
    ) is not None


def build_vat_report(session: Session, start: date, end: date) -> VatReport:
    """The report for a date range, including the checks that need the database."""
    from app.domain.vat.icp import entries_without_contact
    from app.domain.vat.settings import get_vat_settings, kor_overlap

    rows = fetch_rows(session, start, end)
    report = aggregate(rows, start, end)
    extra: list[VatWarning] = []

    eu_entries = sorted({row.entry_id for row, _ in grondslag_lines(rows, "sales", "3b")})
    missing = entries_without_contact(session, eu_entries)
    if missing:
        extra.append(VatWarning("W4", _MESSAGES["W4"], tuple(missing)))

    settings = get_vat_settings(session)
    overlap = kor_overlap(settings, start, end)
    if overlap == "full" and any(r.account_code in _ALL_BTW_ACCOUNTS and not r.vat_code for r in rows):
        ids = sorted({r.entry_id for r in rows if r.account_code in _ALL_BTW_ACCOUNTS and not r.vat_code})
        extra.append(VatWarning(
            "W8",
            "Je gebruikt de KOR maar er staat btw in je boekingen. Controleer of je wel btw hebt "
            "berekend of afgetrokken; met de KOR hoort dat niet.",
            tuple(ids),
        ))
    elif overlap == "partial":
        extra.append(VatWarning(
            "KOR_PARTIAL",
            "Een deel van deze periode valt onder de KOR. Controleer of de btw in je boekingen "
            "klopt; jij beslist of je een aangifte doet.",
        ))
    unfiled = _earlier_unfiled(session, start, settings)
    if unfiled:
        names = ", ".join(p.label for p in unfiled)
        extra.append(VatWarning(
            "W6",
            f"Over {names} staan boekingen, maar die btw-aangifte is nog niet ingediend. "
            "Dien die eerst in; daarna volgt deze.",
        ))
    report.warnings.extend(extra)
    return report


def _earlier_unfiled(session: Session, start: date, settings) -> list:
    """Earlier periods of the same year that have entries, are not fully KOR and are not filed."""
    from app.domain.vat.periods import VatPeriod, periods_of_year, period_range
    from app.domain.vat.settings import kor_overlap
    from app.models import VatReturn

    if start.month == 1 and start.day == 1:
        return []
    filed = list(session.execute(
        select(VatReturn.kind, VatReturn.start_date, VatReturn.end_date).where(VatReturn.year == start.year)
    ))
    kind = filed[0][0] if filed else settings.frequency
    result: list[VatPeriod] = []
    for p in periods_of_year(start.year, kind):
        p_start, p_end = period_range(p)
        if p_end >= start:
            break
        if any(f_start <= p_start and p_end <= f_end for _, f_start, f_end in filed):
            continue
        if kor_overlap(settings, p_start, p_end) == "full":
            continue
        if has_entries(session, p_start, p_end):
            result.append(p)
    return result


def drilldown(session: Session, start: date, end: date, rubriek: str) -> list[DrillLine]:
    return drilldown_rows(fetch_rows(session, start, end), rubriek)


def year_omzet_cents(session: Session, year: int) -> int:
    """Omzet of a year (rubrieken 1a-1e, 3a, 3b) in cents, as a hint for the KOR omzetgrens."""
    report = aggregate(fetch_rows(session, date(year, 1, 1), date(year, 12, 31)), date(year, 1, 1), date(year, 12, 31))
    return sum(l.grondslag_cents for l in report.lines if l.rubriek in ("1a", "1b", "1c", "1d", "1e", "3a", "3b"))
