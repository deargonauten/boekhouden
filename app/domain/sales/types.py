"""Plain dataclasses of the verkoopfacturen (no DB, no Session)."""

from dataclasses import dataclass, field
from datetime import date

INVOICE = "invoice"
CREDIT_NOTE = "credit_note"
CONCEPT = "concept"
DEFINITIEF = "definitief"
SOURCE_TYPE = "verkoopfactuur"
ALLOWED_VAT_CODES = ("NL_21", "NL_9", "NL_0")

BUCKETS = ("not_due", "d1_30", "d31_60", "d61_90", "over_90")
BUCKET_LABELS = {
    "not_due": "Nog niet vervallen",
    "d1_30": "1-30 dagen",
    "d31_60": "31-60 dagen",
    "d61_90": "61-90 dagen",
    "over_90": "Meer dan 90 dagen",
}


@dataclass(frozen=True)
class LineInput:
    """One invoice line as typed by the user. Quantity in thousandths (1,5 = 1500)."""

    description: str
    quantity_milli: int
    unit_price_cents: int
    vat_code: str
    account_id: int | None = None
    unit: str = "stuk"
    original_line_id: int | None = None  # credit notes: the line of the original invoice


@dataclass(frozen=True)
class VatGroup:
    vat_code: str
    rate_bp: int
    base_cents: int  # grondslag
    vat_cents: int


@dataclass(frozen=True)
class Totals:
    line_excl_cents: tuple[int, ...]  # per input line, in input order
    groups: tuple[VatGroup, ...]  # highest rate first
    total_excl_cents: int
    total_vat_cents: int
    total_incl_cents: int


@dataclass(frozen=True)
class DocumentLine:
    description: str
    quantity_milli: int
    unit: str
    unit_price_cents: int
    vat_code: str
    rate_bp: int
    line_excl_cents: int


@dataclass(frozen=True)
class InvoiceDocument:
    """Frozen snapshot of a finalized document; the only input of the PDF renderer."""

    kind: str  # invoice | credit_note
    number: str  # "2026-0001"; "" for a concept preview
    invoice_date: date
    due_date: date
    payment_term_days: int
    seller_name: str
    seller_address_line: str
    seller_postal_code: str
    seller_city: str
    seller_country: str
    seller_kvk: str
    seller_btw_id: str
    seller_iban: str
    buyer_name: str
    buyer_address_line: str
    buyer_postal_code: str
    buyer_city: str
    buyer_country: str
    lines: tuple[DocumentLine, ...]
    vat_groups: tuple[VatGroup, ...]
    total_excl_cents: int
    total_vat_cents: int
    total_incl_cents: int
    seller_email: str | None = None
    seller_phone: str | None = None
    buyer_btw_number: str | None = None
    buyer_kvk: str | None = None
    service_date: date | None = None
    reference: str | None = None
    note: str | None = None
    credited_number: str | None = None  # credit notes: number of the original invoice
    credited_date: date | None = None
    is_concept: bool = False  # preview: PDF is marked CONCEPT


@dataclass(frozen=True)
class AgeingRow:
    """Open amount of one klant split in ageing buckets (days past the vervaldatum, on `today`)."""

    contact_id: int
    contact_name: str
    not_due_cents: int = 0
    d1_30_cents: int = 0
    d31_60_cents: int = 0
    d61_90_cents: int = 0
    over_90_cents: int = 0

    @property
    def total_cents(self) -> int:
        return (
            self.not_due_cents + self.d1_30_cents + self.d31_60_cents
            + self.d61_90_cents + self.over_90_cents
        )

    @property
    def overdue_cents(self) -> int:
        return self.total_cents - self.not_due_cents


@dataclass(frozen=True)
class ReminderDraft:
    """What the herinnering screen shows before it is created."""

    invoice_id: int
    invoice_number: str
    level: int
    title: str
    reminder_date: date
    new_due_date: date
    open_cents: int
    body_text: str
    contact_name: str
    contact_email: str | None = None
    mailto_subject: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReminderDocument:
    """Frozen snapshot for the herinnering PDF (see `pdf.render_reminder_pdf`)."""

    level: int  # 1..3
    title: str  # "Betalingsherinnering" | "Tweede herinnering" | "Laatste aanmaning"
    reminder_date: date
    new_due_date: date
    open_cents: int
    body_text: str
    invoice_number: str
    invoice_date: date
    due_date: date  # original vervaldatum
    seller_name: str
    seller_address_line: str
    seller_postal_code: str
    seller_city: str
    seller_country: str
    seller_kvk: str
    seller_btw_id: str
    seller_iban: str
    buyer_name: str
    buyer_address_line: str
    buyer_postal_code: str
    buyer_city: str
    buyer_country: str
    seller_email: str | None = None
    seller_phone: str | None = None
