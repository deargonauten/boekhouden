"""Pure checks before a verkoopfactuur may be made definitief (art. 35a Wet OB, AC 3/6/15)."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.company.profile import CompanyProfile
from app.domain.sales.errors import (
    CREDIT_LINES_FIXED,
    CREDIT_LINES_FIXED_MESSAGE,
    DATE_ORDER,
    MISSING_FIELD,
    NOT_FINALIZABLE,
    OVER_CREDIT,
    UNSUPPORTED_VAT,
    UNSUPPORTED_VAT_MESSAGE,
    ZERO_TOTAL_MESSAGE,
    SalesError,
    date_order_message,
    over_credit_message,
)
from app.domain.sales.types import ALLOWED_VAT_CODES, LineInput

MAX_NOTE_LENGTH = 500


@dataclass(frozen=True)
class FinalizeInput:
    kind: str
    company: CompanyProfile
    buyer_name: str | None
    buyer_address_line: str | None
    buyer_postal_code: str | None
    buyer_city: str | None
    invoice_date: date | None
    due_date: date | None
    lines: Sequence[LineInput]
    valid_account_ids: Collection[int]  # active, postable revenue accounts
    total_incl_cents: int
    latest_final_date: date | None  # invoice_date of the latest finalized document of that year
    note: str | None = None


def _blank(value: str | None) -> bool:
    return not (value and value.strip())


def _missing(message: str, field: str) -> SalesError:
    return SalesError(MISSING_FIELD, message, field=field)


def check_finalizable(data: FinalizeInput) -> None:
    """Raise a SalesError (Dutch message naming what to fix) if the document cannot be finalized."""
    missing = data.company.missing_for_invoice()
    if missing:
        raise _missing(
            "Vul eerst je bedrijfsgegevens aan onder Instellingen > Bedrijfsgegevens. "
            f"Er ontbreekt: {', '.join(missing)}. Dit moet op elke factuur staan.",
            "company",
        )
    if _blank(data.buyer_name) or any(
        _blank(v) for v in (data.buyer_address_line, data.buyer_postal_code, data.buyer_city)
    ):
        name = (data.buyer_name or "").strip() or "de klant"
        raise _missing(f"Vul het adres van {name} in bij Relaties. Het moet op de factuur staan.", "contact")
    if data.invoice_date is None:
        raise _missing("Vul de factuurdatum in.", "invoice_date")
    if data.due_date is None:
        raise _missing("Vul de vervaldatum in.", "due_date")
    if data.due_date < data.invoice_date:
        raise SalesError(
            NOT_FINALIZABLE,
            "De vervaldatum ligt voor de factuurdatum. Kies dezelfde datum of een latere.",
            field="due_date",
        )
    if data.note and len(data.note) > MAX_NOTE_LENGTH:
        raise SalesError(
            NOT_FINALIZABLE,
            f"De opmerking is te lang (maximaal {MAX_NOTE_LENGTH} tekens).",
            field="note",
        )
    if not data.lines:
        raise _missing("Voeg minstens één regel toe aan de factuur.", "lines")
    for i, line in enumerate(data.lines):
        n = i + 1
        if _blank(line.description):
            raise _missing(f"Regel {n}: vul een omschrijving in.", f"line-{i}-description")
        if line.quantity_milli <= 0:
            raise _missing(f"Regel {n}: het aantal moet groter zijn dan nul.", f"line-{i}-quantity")
        if line.unit_price_cents < 0:
            raise _missing(f"Regel {n}: de prijs mag niet negatief zijn.", f"line-{i}-price")
        if line.vat_code not in ALLOWED_VAT_CODES:
            raise SalesError(UNSUPPORTED_VAT, UNSUPPORTED_VAT_MESSAGE, field=f"line-{i}-vat_code")
        if line.account_id is None:
            raise _missing(f"Regel {n}: kies een omzetrekening.", f"line-{i}-account")
        if line.account_id not in data.valid_account_ids:
            raise _missing(
                f"Regel {n}: de gekozen omzetrekening bestaat niet of staat uit. Kies een andere.",
                f"line-{i}-account",
            )
    if data.total_incl_cents <= 0:
        raise SalesError(NOT_FINALIZABLE, ZERO_TOTAL_MESSAGE, field="lines")
    if data.latest_final_date is not None and data.invoice_date < data.latest_final_date:
        raise SalesError(DATE_ORDER, date_order_message(data.latest_final_date), field="invoice_date")


def check_credit_lines(
    lines: Sequence[tuple[int | None, int]],
    originals: Mapping[int, tuple[int, int]],
) -> None:
    """Credit note lines as (original_line_id, quantity_milli) against the original invoice.

    `originals` maps original line id -> (quantity invoiced, quantity already credited on
    other finalized credit notes). A credit note may only lower quantities or drop lines.
    """
    seen: dict[int, int] = {}
    for original_id, quantity in lines:
        if original_id is None or original_id not in originals:
            raise SalesError(CREDIT_LINES_FIXED, CREDIT_LINES_FIXED_MESSAGE, field="lines")
        seen[original_id] = seen.get(original_id, 0) + quantity
    for original_id, quantity in seen.items():
        invoiced, credited = originals[original_id]
        allowed = max(invoiced - credited, 0)
        if quantity > allowed:
            raise SalesError(OVER_CREDIT, over_credit_message(allowed, credited), field="lines")
