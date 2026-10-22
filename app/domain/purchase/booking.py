"""Pure booking rules for an inkoopfactuur (no database).

`check_bookable` says whether a reviewed extraction can be booked, `build_entry`
turns it into a balanced journal entry, `preview_lines` describes that entry in
plain Dutch. Integer cents only; the printed BTW is used, never recomputed.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.domain.ledger.entries import MAX_DESCRIPTION_LENGTH, NewEntry, NewLine, validate_entry
from app.domain.money import format_euro, require_cents
from app.domain.purchase.errors import (
    ALREADY_BOOKED,
    ALREADY_BOOKED_MESSAGE,
    INVALID_TOTALS,
    MISSING_FIELD,
    NOT_REVIEWED,
    NOT_REVIEWED_MESSAGE,
    UNSUPPORTED_CURRENCY,
    UNSUPPORTED_VAT,
    UNSUPPORTED_VAT_MESSAGE,
    ZERO_AMOUNT,
    BookingError,
)

INVOICE = "invoice"
CREDIT_NOTE = "credit_note"
SOURCE_TYPE = "inkoopfactuur"
# Purchase rubrieken booked automatically: 5b (voorbelasting) or none (0%, geen btw).
SUPPORTED_PURCHASE_RUBRIEKEN = (None, "5b")
# Always refused, also when the rubriek mapping is unknown (verlegd, EU, export).
UNSUPPORTED_VAT_CODES = frozenset({"VERLEGD", "EU_GOEDEREN", "EU_DIENSTEN", "EXPORT"})


@dataclass(frozen=True)
class BookingLineInput:
    description: str | None
    account_id: int | None
    vat_code: str | None
    amount_excl_cents: int | None
    vat_amount_cents: int | None


@dataclass(frozen=True)
class BookingInput:
    supplier_name: str | None
    contact_id: int | None
    invoice_number: str | None
    invoice_date: date | None
    lines: tuple[BookingLineInput, ...]
    total_excl_cents: int | None
    total_vat_cents: int | None
    total_incl_cents: int | None
    kind: str | None = INVOICE  # extraction kind; receipt/unknown are booked as invoice
    currency: str | None = "EUR"
    due_date: date | None = None
    reviewed: bool = True  # extraction.reviewed_at is set
    extraction_ok: bool = True  # extraction.status == 'ok'
    already_booked: bool = False  # document.status == 'geboekt'
    vat_purchase_rubrieken: Mapping[str, str | None] = field(default_factory=dict)

    @property
    def booking_kind(self) -> str:
        return booking_kind(self.kind)

    @property
    def number(self) -> str:
        return (self.invoice_number or "").strip()

    @property
    def description(self) -> str:
        return f"{self.supplier_name or 'Leverancier'} - {self.number}"[:MAX_DESCRIPTION_LENGTH]


@dataclass(frozen=True)
class AccountIds:
    creditors: int  # 3000 Crediteuren
    vat_receivable: int  # 1400 BTW voorbelasting


def booking_kind(kind: str | None) -> str:
    """'credit_note' for a creditnota, else 'invoice' (a bon is booked like a factuur)."""
    return CREDIT_NOTE if kind == CREDIT_NOTE else INVOICE


def invoice_number_key(number: str) -> str:
    """Normalised invoice number for the duplicate guard (trimmed, lower case)."""
    return number.strip().lower()


def is_supported_vat(code: str, rubrieken: Mapping[str, str | None]) -> bool:
    return code not in UNSUPPORTED_VAT_CODES and rubrieken.get(code) in SUPPORTED_PURCHASE_RUBRIEKEN


# --- checks ------------------------------------------------------------------------------
def _missing(message: str, field: str) -> BookingError:
    return BookingError(MISSING_FIELD, message, field=field)


def check_state(data: BookingInput) -> None:
    """Document not booked yet, extraction ok and nagekeken."""
    if data.already_booked:
        raise BookingError(ALREADY_BOOKED, ALREADY_BOOKED_MESSAGE)
    if not data.extraction_ok or not data.reviewed:
        raise BookingError(NOT_REVIEWED, NOT_REVIEWED_MESSAGE)


def check_content(data: BookingInput) -> None:
    """Every field the booking needs is there and the amounts add up."""
    if data.contact_id is None:
        raise _missing(
            "Vul bij het nakijken de leverancier in, zodat duidelijk is aan wie je moet betalen.",
            "supplier_name",
        )
    if data.invoice_date is None:
        raise _missing("Vul bij het nakijken de factuurdatum in.", "invoice_date")
    if not data.number:
        raise _missing("Vul bij het nakijken het factuurnummer in.", "invoice_number")
    currency = (data.currency or "EUR").strip().upper()
    if currency != "EUR":
        raise BookingError(
            UNSUPPORTED_CURRENCY,
            f"Deze factuur is in {currency}. Hier kun je alleen facturen in euro's boeken; "
            "leg deze vast met een handmatige boeking.",
            field="currency",
        )
    if not data.lines:
        raise _missing("Vul bij het nakijken minstens één factuurregel in.", "lines")

    for i, line in enumerate(data.lines):
        n = i + 1
        if line.account_id is None:
            raise _missing(f"Kies bij regel {n} een rekening voor de kosten.", f"line.{i}.account")
        if not line.vat_code:
            raise _missing(f"Kies bij regel {n} een BTW-tarief.", f"line.{i}.vat_code")
        if line.amount_excl_cents is None:
            raise _missing(f"Vul bij regel {n} het bedrag zonder BTW in.", f"line.{i}.amount")
        if line.vat_amount_cents is None:
            raise _missing(
                f"Vul bij regel {n} het BTW-bedrag in (0,00 als er geen BTW is).", f"line.{i}.vat_amount"
            )
        require_cents(line.amount_excl_cents)
        require_cents(line.vat_amount_cents)
        if line.amount_excl_cents == 0:
            raise BookingError(
                ZERO_AMOUNT,
                f"Regel {n} heeft een bedrag van {format_euro(0)}. Vul het bedrag in of haal de regel weg.",
                field=f"line.{i}.amount",
            )
        if not is_supported_vat(line.vat_code, data.vat_purchase_rubrieken):
            raise BookingError(UNSUPPORTED_VAT, UNSUPPORTED_VAT_MESSAGE, field=f"line.{i}.vat_code")

    for value, label, name in (
        (data.total_excl_cents, "het totaal zonder BTW", "total_excl"),
        (data.total_vat_cents, "het totale BTW-bedrag", "total_vat"),
        (data.total_incl_cents, "het totaal inclusief BTW", "total_incl"),
    ):
        if value is None:
            raise _missing(f"Vul bij het nakijken {label} in.", name)
        require_cents(value)

    excl = sum(l.amount_excl_cents for l in data.lines)
    vat = sum(l.vat_amount_cents for l in data.lines)
    if excl != data.total_excl_cents:
        raise BookingError(
            INVALID_TOTALS,
            f"De regels tellen op tot {format_euro(excl)} zonder BTW, maar het totaal is "
            f"{format_euro(data.total_excl_cents)}. Pas bij het nakijken een regel of het totaal aan.",
            field="total_excl",
        )
    if vat != data.total_vat_cents:
        raise BookingError(
            INVALID_TOTALS,
            f"De BTW van de regels telt op tot {format_euro(vat)}, maar het BTW-totaal is "
            f"{format_euro(data.total_vat_cents)}. Pas bij het nakijken een regel of het totaal aan.",
            field="total_vat",
        )
    if data.total_excl_cents + data.total_vat_cents != data.total_incl_cents:
        raise BookingError(
            INVALID_TOTALS,
            f"Zonder BTW plus BTW is {format_euro(data.total_excl_cents + data.total_vat_cents)}, "
            f"maar het totaal is {format_euro(data.total_incl_cents)}. "
            "Pas bij het nakijken de totalen aan.",
            field="total_incl",
        )
    if data.total_incl_cents <= 0:
        raise BookingError(
            INVALID_TOTALS,
            f"Het totaal van de factuur moet groter zijn dan {format_euro(0)}. "
            "Is het een creditnota? Kies dat dan bij het nakijken.",
            field="total_incl",
        )


def check_bookable(data: BookingInput) -> None:
    """Raise BookingError (plain Dutch, with the field to fix) when it cannot be booked."""
    check_state(data)
    check_content(data)


# --- entry ----------------------------------------------------------------------------------
def _line(account_id: int, amount: int, *, debit: bool, description: str | None, vat_code=None) -> NewLine:
    """A line on the debit (or credit) side; a negative amount goes to the other side."""
    if amount < 0:
        amount, debit = -amount, not debit
    if debit:
        return NewLine(account_id, debit_cents=amount, description=description, vat_code=vat_code)
    return NewLine(account_id, credit_cents=amount, description=description, vat_code=vat_code)


def build_entry(data: BookingInput, accounts: AccountIds, journal_id: int) -> NewEntry:
    """Balanced entry: costs + voorbelasting on one side, crediteuren on the other.

    Invoice: debit each line's account (grondslag, with the line's btw-code), debit 1400
    per btw-code with BTW (no btw-code on that line), credit 3000 for the total. A
    creditnota swaps debit and credit; amounts stay positive.
    """
    check_content(data)
    costs_debit = data.booking_kind == INVOICE
    lines: list[NewLine] = [
        _line(
            l.account_id,
            l.amount_excl_cents,
            debit=costs_debit,
            description=(l.description or "").strip() or data.description,
            vat_code=l.vat_code,
        )
        for l in data.lines
    ]
    vat_per_code: dict[str, int] = {}
    for l in data.lines:
        vat_per_code[l.vat_code] = vat_per_code.get(l.vat_code, 0) + l.vat_amount_cents
    for code, amount in vat_per_code.items():
        if amount:
            lines.append(
                _line(accounts.vat_receivable, amount, debit=costs_debit, description=f"Voorbelasting {code}")
            )
    lines.append(
        _line(accounts.creditors, data.total_incl_cents, debit=not costs_debit, description=data.description)
    )
    entry = NewEntry(
        journal_id=journal_id,
        booking_date=data.invoice_date,
        description=data.description,
        lines=lines,
        reference=data.number,
    )
    validate_entry(entry)
    return entry


# --- preview ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class PreviewRow:
    label: str  # plain Dutch: "Kosten", "BTW die je terugkrijgt", "Nog te betalen aan ..."
    description: str | None
    account_id: int
    account_code: str
    account_name: str
    vat_code: str | None
    vat_label: str | None  # e.g. "21%"
    amount_cents: int  # always positive
    side: str  # 'debet' | 'credit'
    term: str | None  # glossary key for the info icon (voorbelasting, crediteuren)


@dataclass(frozen=True)
class PreviewTable:
    rows: list[PreviewRow]
    summary: str
    total_to_pay_cents: int  # negative for a creditnota (you get money back)


def preview_lines(
    data: BookingInput,
    accounts: AccountIds,
    account_labels: Mapping[int, tuple[str, str]],
    vat_labels: Mapping[str, str],
) -> PreviewTable:
    """The rows of `build_entry` in plain Dutch, plus a one-sentence summary.

    `account_labels` maps account id -> (code, name); `vat_labels` btw-code -> "21%".
    """
    entry = build_entry(data, accounts, journal_id=0)
    supplier = data.supplier_name or "de leverancier"
    credit_note = data.booking_kind == CREDIT_NOTE
    rows = []
    for l in entry.lines:
        code, name = account_labels.get(l.account_id, ("", ""))
        if l.account_id == accounts.creditors:
            label = f"Krijg je terug van {supplier}" if credit_note else f"Nog te betalen aan {supplier}"
            term, description = "crediteuren", None
        elif l.account_id == accounts.vat_receivable and l.vat_code is None:
            label, term, description = "BTW die je terugkrijgt", "voorbelasting", None
        else:
            label, term, description = "Kosten", None, l.description
        rows.append(
            PreviewRow(
                label=label,
                description=description,
                account_id=l.account_id,
                account_code=code,
                account_name=name,
                vat_code=l.vat_code,
                vat_label=vat_labels.get(l.vat_code) if l.vat_code else None,
                amount_cents=l.debit_cents or l.credit_cents,
                side="debet" if l.debit_cents else "credit",
                term=term,
            )
        )
    excl, vat, incl = data.total_excl_cents, data.total_vat_cents, data.total_incl_cents
    if credit_note:
        summary = (
            f"Creditnota van {supplier}: kosten {format_euro(excl)} minder, "
            f"BTW {format_euro(vat)} minder terug, je krijgt {format_euro(incl)} terug."
        )
    else:
        vat_text = f"BTW {format_euro(vat)}" if vat else "geen BTW"
        summary = f"Kosten {format_euro(excl)}, {vat_text}, nog te betalen aan {supplier} {format_euro(incl)}."
    return PreviewTable(rows=rows, summary=summary, total_to_pay_cents=-incl if credit_note else incl)
