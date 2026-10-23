"""Contract between the extractor backends, the service and the web layer."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from app.domain.relations import ExtractedContact

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class AccountHint:
    code: str
    name: str


@dataclass(frozen=True)
class ExtractionRequest:
    content: bytes
    content_type: str
    filename: str
    accounts: tuple[AccountHint, ...]  # active, postable, type=expense
    vat_codes: tuple[str, ...]  # active vat_code.code values


@dataclass(frozen=True)
class ExtractedLine:
    description: str | None = None
    amount_excl_cents: int | None = None
    vat_code: str | None = None
    vat_amount_cents: int | None = None
    suggested_account_code: str | None = None
    confidence: Mapping[str, Confidence] = field(default_factory=dict)
    source_text: str | None = None  # verbatim passage of the document this line was read from


@dataclass(frozen=True)
class ExtractedInvoice:
    kind: str = "invoice"  # invoice | credit_note | receipt | unknown
    supplier: ExtractedContact = ExtractedContact()
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = "EUR"
    total_excl_cents: int | None = None
    total_vat_cents: int | None = None
    total_incl_cents: int | None = None
    lines: tuple[ExtractedLine, ...] = ()
    confidence: Mapping[str, Confidence] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    raw: str | None = None  # raw model output, stored as raw_json


class InvoiceExtractor(Protocol):
    name: str
    model: str | None

    def extract(self, request: ExtractionRequest) -> ExtractedInvoice: ...
