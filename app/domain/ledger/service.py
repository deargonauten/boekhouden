"""DB-using ledger service.

Service functions flush but never commit; the caller (route handler / test)
commits on success and rolls back on exception.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.domain.errors import LedgerError
from app.domain.ledger.entries import NewEntry, NewLine, build_storno, validate_entry
from app.domain.ledger.periods import generate_periods
from app.models import (
    Account,
    FiscalYear,
    Journal,
    JournalEntry,
    JournalLine,
    Period,
    VatCode,
)

ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")
JOURNAL_TYPES = ("verkoop", "inkoop", "bank", "kas", "memoriaal")
ENTRY_KINDS = ("normal", "opening", "storno")


# --- read models -----------------------------------------------------------


@dataclass
class Page:
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))


@dataclass
class EntryRow:
    id: int
    entry_number: str
    booking_date: date
    journal_code: str
    description: str
    kind: str
    total_cents: int
    reverses_entry_id: int | None = None
    reverses_number: str | None = None
    reversed_by_id: int | None = None
    reversed_by_number: str | None = None


@dataclass
class LineView:
    id: int
    line_no: int
    account_id: int
    account_code: str
    account_name: str
    debit_cents: int
    credit_cents: int
    description: str | None
    vat_code: str | None


@dataclass
class EntryDetail:
    entry: JournalEntry
    journal_code: str
    journal_name: str
    lines: list[LineView]
    total_cents: int
    original: JournalEntry | None = None
    reversed_by: JournalEntry | None = None

    @property
    def is_reversible(self) -> bool:
        return self.entry.kind != "storno" and self.reversed_by is None


@dataclass
class FiscalYearView:
    id: int
    year: int
    start_date: date
    end_date: date
    status: str
    periods: list[Period] = field(default_factory=list)


@dataclass(frozen=True)
class TrialBalanceRow:
    account_id: int
    code: str
    name: str
    debit_cents: int
    credit_cents: int


# --- helpers ---------------------------------------------------------------


def _today() -> date:
    return date.today()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _error(code: str, message: str) -> LedgerError:
    return LedgerError(code, message)


def _find_period(session: Session, day: date) -> Period:
    """Return the open period containing `day`, or raise."""
    period = session.scalar(
        select(Period).where(Period.start_date <= day, Period.end_date >= day)
    )
    if period is None:
        raise _error(
            "NO_OPEN_PERIOD",
            f"Er is geen boekjaar voor {day:%d-%m-%Y}. Maak eerst het boekjaar aan "
            "onder Instellingen > Boekjaren.",
        )
    if period.status != "open":
        raise _error(
            "PERIOD_LOCKED",
            f"De periode van {day:%d-%m-%Y} is vergrendeld; er kan niet meer in worden geboekt.",
        )
    return period


def _check_accounts(session: Session, lines: list[NewLine], *, check_active: bool) -> None:
    ids = {l.account_id for l in lines}
    accounts = {a.id: a for a in session.scalars(select(Account).where(Account.id.in_(ids)))}
    for l in lines:
        a = accounts.get(l.account_id)
        if a is None:
            raise _error("ACCOUNT_NOT_FOUND", f"Grootrekening {l.account_id} bestaat niet.")
        if not a.is_postable:
            raise _error(
                "ACCOUNT_NOT_POSTABLE",
                f"Op grootrekening {a.code} {a.name} kan niet worden geboekt.",
            )
        if check_active and not a.is_active:
            raise _error(
                "ACCOUNT_INACTIVE",
                f"Grootrekening {a.code} {a.name} is niet actief.",
            )


def _check_vat_codes(session: Session, lines: list[NewLine], *, check_active: bool) -> None:
    codes = {l.vat_code for l in lines if l.vat_code}
    if not codes:
        return
    found = {v.code: v for v in session.scalars(select(VatCode).where(VatCode.code.in_(codes)))}
    for code in sorted(codes):
        v = found.get(code)
        if v is None or (check_active and not v.is_active):
            raise _error("INVALID_VAT_CODE", f"Onbekende of niet-actieve btw-code: {code}.")


def _next_number(session: Session, journal_id: int, fiscal_year_id: int) -> int:
    return session.execute(
        text(
            "INSERT INTO entry_sequence(journal_id, fiscal_year_id, last_number) "
            "VALUES (:j, :f, 1) "
            "ON CONFLICT(journal_id, fiscal_year_id) "
            "DO UPDATE SET last_number = last_number + 1 "
            "RETURNING last_number"
        ),
        {"j": journal_id, "f": fiscal_year_id},
    ).scalar_one()


def _insert_lines(session: Session, entry_id: int, lines: list[NewLine]) -> None:
    for no, l in enumerate(lines, start=1):
        session.add(
            JournalLine(
                entry_id=entry_id,
                line_no=no,
                account_id=l.account_id,
                debit_cents=l.debit_cents,
                credit_cents=l.credit_cents,
                description=l.description,
                vat_code=l.vat_code,
            )
        )
    session.flush()


def _post(
    session: Session,
    new: NewEntry,
    *,
    reverses_entry_id: int | None = None,
    strict_refs: bool = True,
) -> JournalEntry:
    validate_entry(new)
    if new.kind not in ENTRY_KINDS:
        raise _error("INVALID_ENTRY", f"Onbekend boekingssoort: {new.kind}.")
    journal = session.get(Journal, new.journal_id)
    if journal is None:
        raise _error("JOURNAL_NOT_FOUND", "Dagboek bestaat niet.")
    if strict_refs and not journal.is_active:
        raise _error("JOURNAL_INACTIVE", f"Dagboek {journal.code} is niet actief.")
    if new.kind == "opening" and journal.type != "memoriaal":
        raise _error(
            "INVALID_ENTRY", "Een beginbalans-boeking kan alleen in het memoriaal worden gemaakt."
        )
    _check_accounts(session, new.lines, check_active=strict_refs)
    _check_vat_codes(session, new.lines, check_active=strict_refs)
    period = _find_period(session, new.booking_date)

    # Savepoint: a failure after the sequence bump must not consume a number.
    with session.begin_nested():
        seq = _next_number(session, journal.id, period.fiscal_year_id)
        year = session.scalar(select(FiscalYear.year).where(FiscalYear.id == period.fiscal_year_id))
        entry = JournalEntry(
            journal_id=journal.id,
            period_id=period.id,
            entry_number=f"{journal.code}-{year}-{seq:04d}",
            booking_date=new.booking_date,
            description=new.description,
            reference=new.reference,
            kind=new.kind,
            reverses_entry_id=reverses_entry_id,
        )
        session.add(entry)
        session.flush()
        _insert_lines(session, entry.id, new.lines)
    return entry


# --- posting ---------------------------------------------------------------


def post_entry(session: Session, new: NewEntry) -> JournalEntry:
    if new.kind == "storno":
        raise _error("INVALID_ENTRY", "Een stornoboeking maak je met 'Stornoboeking maken'.")
    return _post(session, new)


def _entry_lines(session: Session, entry_id: int) -> list[JournalLine]:
    return list(
        session.scalars(
            select(JournalLine).where(JournalLine.entry_id == entry_id).order_by(JournalLine.line_no)
        )
    )


def reverse_entry(
    session: Session,
    entry_id: int,
    booking_date: date | None = None,
    description: str | None = None,
) -> JournalEntry:
    original = session.get(JournalEntry, entry_id)
    if original is None:
        raise _error("ENTRY_NOT_FOUND", "Boeking niet gevonden.")
    if original.kind == "storno":
        raise _error(
            "CANNOT_REVERSE_STORNO",
            "Een stornoboeking kan niet worden gestorneerd; maak een nieuwe boeking.",
        )
    existing = session.scalar(
        select(JournalEntry.entry_number).where(JournalEntry.reverses_entry_id == original.id)
    )
    if existing is not None:
        raise _error(
            "ALREADY_REVERSED",
            f"Boeking {original.entry_number} is al gestorneerd ({existing}).",
        )
    if booking_date is None:
        orig_period = session.get(Period, original.period_id)
        booking_date = original.booking_date if orig_period.status == "open" else _today()
    lines = [
        NewLine(
            account_id=l.account_id,
            debit_cents=l.debit_cents,
            credit_cents=l.credit_cents,
            description=l.description,
            vat_code=l.vat_code,
        )
        for l in _entry_lines(session, original.id)
    ]
    new = NewEntry(
        journal_id=original.journal_id,
        booking_date=booking_date,
        description=description or f"Storno {original.entry_number}",
        lines=build_storno(lines),
        reference=original.reference,
        kind="storno",
    )
    # A storno must stay possible after accounts/VAT codes/dagboek are deactivated.
    return _post(session, new, reverses_entry_id=original.id, strict_refs=False)


# --- boekjaar / periodes ---------------------------------------------------


def create_fiscal_year(session: Session, year: int) -> FiscalYear:
    if session.scalar(select(FiscalYear.id).where(FiscalYear.year == year)) is not None:
        raise _error("YEAR_EXISTS", f"Boekjaar {year} bestaat al.")
    fy = FiscalYear(year=year, start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="open")
    session.add(fy)
    session.flush()
    for spec in generate_periods(year):
        session.add(
            Period(
                fiscal_year_id=fy.id,
                number=spec.number,
                start_date=spec.start_date,
                end_date=spec.end_date,
                status="open",
            )
        )
    session.flush()
    return fy


def _close_if_all_locked(session: Session, fiscal_year_id: int) -> None:
    open_count = session.scalar(
        select(func.count()).select_from(Period).where(
            Period.fiscal_year_id == fiscal_year_id, Period.status != "locked"
        )
    )
    if open_count == 0:
        fy = session.get(FiscalYear, fiscal_year_id)
        if fy.status != "closed":
            fy.status = "closed"
            session.flush()


def lock_period(session: Session, period_id: int) -> Period:
    period = session.get(Period, period_id)
    if period is None:
        raise _error("PERIOD_NOT_FOUND", "Periode niet gevonden.")
    if period.status != "locked":
        period.status = "locked"
        period.locked_at = _now()
        session.flush()
    _close_if_all_locked(session, period.fiscal_year_id)
    return period


def close_fiscal_year(session: Session, year: int) -> FiscalYear:
    fy = session.scalar(select(FiscalYear).where(FiscalYear.year == year))
    if fy is None:
        raise _error("YEAR_NOT_FOUND", f"Boekjaar {year} bestaat niet.")
    for p in session.scalars(select(Period).where(Period.fiscal_year_id == fy.id)):
        if p.status != "locked":
            p.status = "locked"
            p.locked_at = _now()
    session.flush()
    _close_if_all_locked(session, fy.id)
    return fy


# --- grootboek / dagboeken -------------------------------------------------


def add_account(
    session: Session,
    *,
    code: str,
    name: str,
    type: str,
    rgs_code: str | None = None,
    default_vat_code: str | None = None,
    is_postable: bool = True,
) -> Account:
    code = (code or "").strip()
    name = (name or "").strip()
    if not re.fullmatch(r"[0-9]{4}", code):
        raise _error("INVALID_ACCOUNT", "De rekeningcode moet uit precies 4 cijfers bestaan.")
    if not name:
        raise _error("INVALID_ACCOUNT", "Een grootrekening heeft een naam nodig.")
    if type not in ACCOUNT_TYPES:
        raise _error("INVALID_ACCOUNT", f"Onbekend rekeningtype: {type}.")
    if session.scalar(select(Account.id).where(Account.code == code)) is not None:
        raise _error("DUPLICATE_CODE", f"Rekeningcode {code} bestaat al.")
    if default_vat_code is not None and session.get(VatCode, default_vat_code) is None:
        raise _error("INVALID_VAT_CODE", f"Onbekende btw-code: {default_vat_code}.")
    account = Account(
        code=code,
        name=name,
        type=type,
        rgs_code=rgs_code,
        default_vat_code=default_vat_code,
        is_postable=is_postable,
        is_active=True,
        is_system=False,
    )
    session.add(account)
    session.flush()
    return account


def _get_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise _error("ACCOUNT_NOT_FOUND", "Grootrekening bestaat niet.")
    return account


def set_account_active(session: Session, account_id: int, active: bool) -> Account:
    account = _get_account(session, account_id)
    account.is_active = active
    session.flush()
    return account


def rename_account(session: Session, account_id: int, name: str) -> Account:
    account = _get_account(session, account_id)
    if account.is_system:
        raise _error("SYSTEM_ACCOUNT", "Een systeemrekening kan niet worden hernoemd.")
    name = (name or "").strip()
    if not name:
        raise _error("INVALID_ACCOUNT", "Een grootrekening heeft een naam nodig.")
    account.name = name
    session.flush()
    return account


def delete_account(session: Session, account_id: int) -> None:
    account = _get_account(session, account_id)
    if account.is_system:
        raise _error("SYSTEM_ACCOUNT", "Een systeemrekening kan niet worden verwijderd.")
    in_use = session.scalar(
        select(JournalLine.id).where(JournalLine.account_id == account_id).limit(1)
    ) or session.scalar(select(Journal.id).where(Journal.account_id == account_id).limit(1))
    if in_use is not None:
        raise _error(
            "ACCOUNT_IN_USE",
            f"Grootrekening {account.code} is in gebruik; deactiveer de rekening in plaats van verwijderen.",
        )
    session.delete(account)
    session.flush()


def add_journal(
    session: Session,
    *,
    code: str,
    name: str,
    type: str,
    account_id: int | None = None,
) -> Journal:
    code = (code or "").strip()
    name = (name or "").strip()
    if not re.fullmatch(r"[A-Z0-9]{1,6}", code):
        raise _error("INVALID_JOURNAL", "De dagboekcode bestaat uit 1 tot 6 hoofdletters of cijfers.")
    if not name:
        raise _error("INVALID_JOURNAL", "Een dagboek heeft een naam nodig.")
    if type not in JOURNAL_TYPES:
        raise _error("INVALID_JOURNAL", f"Onbekend dagboektype: {type}.")
    if type in ("bank", "kas"):
        account = session.get(Account, account_id) if account_id is not None else None
        if account is None or account.type != "asset" or not account.is_active:
            raise _error(
                "INVALID_JOURNAL",
                "Een bank- of kasdagboek heeft een actieve grootrekening van het type activa nodig.",
            )
    else:
        account_id = None
    if session.scalar(select(Journal.id).where(Journal.code == code)) is not None:
        raise _error("DUPLICATE_CODE", f"Dagboekcode {code} bestaat al.")
    journal = Journal(code=code, name=name, type=type, account_id=account_id, is_active=True)
    session.add(journal)
    session.flush()
    return journal


def set_journal_active(session: Session, journal_id: int, active: bool) -> Journal:
    journal = session.get(Journal, journal_id)
    if journal is None:
        raise _error("JOURNAL_NOT_FOUND", "Dagboek bestaat niet.")
    journal.is_active = active
    session.flush()
    return journal


# --- queries ---------------------------------------------------------------


def list_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.code)))


def list_journals(session: Session) -> list[Journal]:
    return list(session.scalars(select(Journal).order_by(Journal.id)))


def list_vat_codes(session: Session) -> list[VatCode]:
    return list(session.scalars(select(VatCode).order_by(VatCode.code)))


def list_fiscal_years(session: Session) -> list[FiscalYearView]:
    years = list(session.scalars(select(FiscalYear).order_by(FiscalYear.year.desc())))
    periods: dict[int, list[Period]] = {}
    for p in session.scalars(select(Period).order_by(Period.fiscal_year_id, Period.number)):
        periods.setdefault(p.fiscal_year_id, []).append(p)
    return [
        FiscalYearView(y.id, y.year, y.start_date, y.end_date, y.status, periods.get(y.id, []))
        for y in years
    ]


def list_entries(
    session: Session,
    journal_code: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> Page:
    page = max(1, page)
    totals = (
        select(JournalLine.entry_id, func.sum(JournalLine.debit_cents).label("total"))
        .group_by(JournalLine.entry_id)
        .subquery()
    )
    storno = aliased(JournalEntry)
    original = aliased(JournalEntry)
    stmt = (
        select(
            JournalEntry,
            Journal.code,
            totals.c.total,
            original.entry_number,
            storno.id,
            storno.entry_number,
        )
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .outerjoin(totals, totals.c.entry_id == JournalEntry.id)
        .outerjoin(original, original.id == JournalEntry.reverses_entry_id)
        .outerjoin(storno, storno.reverses_entry_id == JournalEntry.id)
    )
    count = select(func.count()).select_from(JournalEntry).join(Journal, Journal.id == JournalEntry.journal_id)
    if journal_code:
        stmt = stmt.where(Journal.code == journal_code)
        count = count.where(Journal.code == journal_code)
    total = session.scalar(count)
    rows = session.execute(
        stmt.order_by(JournalEntry.id.desc()).limit(per_page).offset((page - 1) * per_page)
    ).all()
    items = [
        EntryRow(
            id=e.id,
            entry_number=e.entry_number,
            booking_date=e.booking_date,
            journal_code=jcode,
            description=e.description,
            kind=e.kind,
            total_cents=tot or 0,
            reverses_entry_id=e.reverses_entry_id,
            reverses_number=orig_no,
            reversed_by_id=st_id,
            reversed_by_number=st_no,
        )
        for e, jcode, tot, orig_no, st_id, st_no in rows
    ]
    return Page(items=items, page=page, per_page=per_page, total=total)


def get_entry(session: Session, entry_id: int) -> EntryDetail | None:
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        return None
    journal = session.get(Journal, entry.journal_id)
    rows = session.execute(
        select(JournalLine, Account.code, Account.name)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    lines = [
        LineView(
            id=l.id,
            line_no=l.line_no,
            account_id=l.account_id,
            account_code=code,
            account_name=name,
            debit_cents=l.debit_cents,
            credit_cents=l.credit_cents,
            description=l.description,
            vat_code=l.vat_code,
        )
        for l, code, name in rows
    ]
    original = session.get(JournalEntry, entry.reverses_entry_id) if entry.reverses_entry_id else None
    reversed_by = session.scalar(select(JournalEntry).where(JournalEntry.reverses_entry_id == entry_id))
    return EntryDetail(
        entry=entry,
        journal_code=journal.code,
        journal_name=journal.name,
        lines=lines,
        total_cents=sum(l.debit_cents for l in lines),
        original=original,
        reversed_by=reversed_by,
    )


def trial_balance(
    session: Session,
    *,
    fiscal_year: int | None = None,
    period_ids: list[int] | None = None,
    up_to: date | None = None,
) -> list[TrialBalanceRow]:
    if period_ids is not None and not period_ids:
        return []
    debit = func.sum(JournalLine.debit_cents)
    credit = func.sum(JournalLine.credit_cents)
    stmt = (
        select(Account.id, Account.code, Account.name, debit, credit)
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .group_by(Account.id, Account.code, Account.name)
        .order_by(Account.code)
    )
    if fiscal_year is not None:
        stmt = stmt.join(Period, Period.id == JournalEntry.period_id).join(
            FiscalYear, FiscalYear.id == Period.fiscal_year_id
        ).where(FiscalYear.year == fiscal_year)
    if period_ids is not None:
        stmt = stmt.where(JournalEntry.period_id.in_(period_ids))
    if up_to is not None:
        stmt = stmt.where(JournalEntry.booking_date <= up_to)
    return [TrialBalanceRow(i, c, n, int(d), int(cr)) for i, c, n, d, cr in session.execute(stmt)]
