"""ICP-opgaaf: EU sales (rubriek 3b) per klant (landcode + btw-nummer)."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import vat_error
from app.domain.money import format_euro
from app.domain.relations.validation import normalize_btw_number, normalize_name
from app.domain.vat.report import (
    VatWarning,
    aggregate,
    fetch_rows,
    grondslag_lines,
)
from app.models import Contact, JournalEntry, Period, SalesInvoice, VatEntryContact, VatReturn

DIENSTEN_CODE = "EU_DIENSTEN"
_PREFIX = re.compile(r"^[A-Z]{2}")

MISSING_NUMBER_FIX = (
    "Vul het btw-nummer van de klant in bij Relaties en koppel de klant daarna opnieuw aan de boeking."
)
NL_FIX = (
    "Deze klant zit in Nederland en hoort niet in de ICP-opgaaf. Controleer het land en btw-nummer "
    "van de klant bij Relaties, of kies een andere btw-code voor de verkoop."
)


@dataclass(frozen=True)
class IcpRow:
    country: str  # landcode, e.g. 'DE'
    btw_number: str  # without the landcode prefix; '' when unknown
    goederen_cents: int
    diensten_cents: int
    driehoek_cents: int = 0  # not supported, always 0
    contact_id: int | None = None
    name: str | None = None
    issue: str | None = None  # plain-Dutch fix when the row is incomplete ("Onvolledig")
    entry_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class IcpUnassigned:
    """An EU-sale entry without a klant ('Nog geen klant gekoppeld')."""

    entry_id: int
    entry_number: str
    booking_date: date
    description: str
    goederen_cents: int
    diensten_cents: int


@dataclass
class IcpReport:
    period_start: date
    period_end: date
    rows: list[IcpRow] = field(default_factory=list)  # complete and incomplete (issue set)
    unassigned: list[IcpUnassigned] = field(default_factory=list)
    warnings: list[VatWarning] = field(default_factory=list)


@dataclass(frozen=True)
class _Klant:
    country: str
    number: str
    name: str | None
    contact_id: int | None


def split_btw_number(raw: str | None, fallback_country: str | None) -> tuple[str, str]:
    """(landcode, number without prefix) from a btw-nummer; the landcode falls back to the country."""
    number = normalize_btw_number(raw) or ""
    if number and _PREFIX.match(number):
        return number[:2], number[2:]
    return (fallback_country or "").strip().upper(), number


def _resolve(session: Session, entry_ids: list[int]) -> dict[int, _Klant | None]:
    """Klant per entry: sales invoice buyer, then coupling; a storno follows its original."""
    if not entry_ids:
        return {}
    originals = {
        eid: reverses for eid, reverses in session.execute(
            select(JournalEntry.id, JournalEntry.reverses_entry_id).where(JournalEntry.id.in_(entry_ids))
        )
    }
    lookup = {eid: (originals.get(eid) or eid) for eid in entry_ids}
    ids = set(lookup.values())
    invoices = {
        inv.journal_entry_id: inv
        for inv in session.scalars(select(SalesInvoice).where(SalesInvoice.journal_entry_id.in_(ids)))
    }
    couplings = {
        c.entry_id: c.contact_id
        for c in session.scalars(select(VatEntryContact).where(VatEntryContact.entry_id.in_(ids)))
    }
    contacts = {
        c.id: c
        for c in session.scalars(select(Contact).where(Contact.id.in_(set(couplings.values()))))
    }
    result: dict[int, _Klant | None] = {}
    for eid, original in lookup.items():
        inv = invoices.get(original)
        if inv is not None:
            country, number = split_btw_number(inv.buyer_btw_number, inv.buyer_country)
            result[eid] = _Klant(country, number, inv.buyer_name, inv.contact_id)
        elif original in couplings:
            c = contacts[couplings[original]]
            country, number = split_btw_number(c.btw_number, c.country)
            result[eid] = _Klant(country, number, c.name, c.id)
        else:
            result[eid] = None
    return result


def entries_without_contact(session: Session, entry_ids: list[int]) -> list[int]:
    resolved = _resolve(session, entry_ids)
    return sorted(eid for eid in entry_ids if resolved.get(eid) is None)


def build_icp(session: Session, start: date, end: date) -> IcpReport:
    rows = fetch_rows(session, start, end)
    report = IcpReport(start, end)

    per_entry: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # entry -> [goederen, diensten]
    unclear: set[int] = set()
    info: dict[int, tuple[str, date, str]] = {}
    for row, amount in grondslag_lines(rows, "sales", "3b"):
        if row.vat_code == DIENSTEN_CODE:
            per_entry[row.entry_id][1] += amount
        else:
            per_entry[row.entry_id][0] += amount
            if row.vat_code != "EU_GOEDEREN":
                unclear.add(row.entry_id)
        info[row.entry_id] = (row.entry_number, row.booking_date, row.description)

    resolved = _resolve(session, sorted(per_entry))
    groups: dict[tuple, dict] = {}
    for eid in sorted(per_entry):
        goederen, diensten = per_entry[eid]
        klant = resolved[eid]
        if klant is None:
            if goederen or diensten:
                number, day, description = info[eid]
                report.unassigned.append(IcpUnassigned(eid, number, day, description, goederen, diensten))
            continue
        key = (klant.country, klant.number, klant.contact_id if not klant.number else None)
        g = groups.setdefault(key, {"klant": klant, "goederen": 0, "diensten": 0, "entries": []})
        g["goederen"] += goederen
        g["diensten"] += diensten
        g["entries"].append(eid)

    for (country, number, _), g in groups.items():
        if not g["goederen"] and not g["diensten"]:
            continue
        issue = MISSING_NUMBER_FIX if not number else NL_FIX if country == "NL" else None
        klant = g["klant"]
        report.rows.append(IcpRow(
            country, number, g["goederen"], g["diensten"], 0, klant.contact_id, klant.name, issue,
            tuple(g["entries"]),
        ))
    report.rows.sort(key=lambda r: (r.issue is not None, r.country, r.btw_number, r.name or ""))

    if unclear:
        report.warnings.append(VatWarning(
            "ICP_UNCLEAR",
            "Bij deze verkopen is niet duidelijk of het goederen of diensten zijn; ze staan bij "
            "goederen. Kies de btw-code 'EU-diensten' als het diensten zijn.",
            tuple(sorted(unclear)),
        ))
    total = sum(r.goederen_cents + r.diensten_cents for r in report.rows) + sum(
        u.goederen_cents + u.diensten_cents for u in report.unassigned
    )
    expected = next(l.grondslag_cents for l in aggregate(rows, start, end).lines if l.rubriek == "3b")
    if total != expected:
        diff = expected - total
        report.warnings.append(VatWarning(
            "ICP_MISMATCH",
            f"ICP en rubriek 3b komen niet overeen: het verschil is {format_euro(diff)}. "
            "Controleer de klanten bij de EU-verkopen.",
        ))
    return report


def couple_entry_contact(session: Session, entry_id: int, contact_id: int) -> None:
    """Couple (or re-couple) a klant to a booked entry; refused once the period is locked or filed."""
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        raise vat_error("VAT_ENTRY_NOT_FOUND")
    if session.get(Contact, contact_id) is None:
        raise vat_error("VAT_CONTACT_NOT_FOUND")
    period = session.get(Period, entry.period_id)
    filed = session.scalar(
        select(VatReturn.id).where(VatReturn.start_date <= entry.booking_date, VatReturn.end_date >= entry.booking_date)
    )
    if (period is not None and period.status == "locked") or filed is not None:
        raise vat_error("VAT_ENTRY_LOCKED")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = session.get(VatEntryContact, entry_id)
    if row is None:
        session.add(VatEntryContact(entry_id=entry_id, contact_id=contact_id, updated_at=now))
    else:
        row.contact_id, row.updated_at = contact_id, now
    session.flush()


def suggest_contact(session: Session, entry_id: int) -> Contact | None:
    """The active klant whose name occurs in the entry description (longest match), or None."""
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        return None
    text = f" {normalize_name(entry.description)} "
    best: Contact | None = None
    for c in session.scalars(select(Contact).where(Contact.is_active.is_(True), Contact.is_customer.is_(True))):
        if len(c.name_key) >= 3 and f" {c.name_key} " in text:
            if best is None or len(c.name_key) > len(best.name_key):
                best = c
    return best
