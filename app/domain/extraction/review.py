"""The nakijken form: raw user input -> validated, typed values.

Pure (no database): the service passes in the accounts and BTW codes that
exist. All problems of a form are collected into ONE `ReviewValidationError`
whose `messages` are plain Dutch and whose `fields` map form fields
(`invoice_date`, `total_excl`, `line.1.amount`, ...) to their message.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.errors import LedgerError, RelationError, ReviewValidationError
from app.domain.fx import BASE_CURRENCY, format_amount, parse_rate
from app.domain.extraction.suggestions import AccountRef, resolve_account_code
from app.domain.money import parse_euro
from app.domain.vat.rates import parse_rate_bp
from app.domain.relations.validation import (
    validate_btw_number,
    validate_country,
    validate_iban,
    validate_kvk,
    validate_postal_code,
)

KINDS = ("invoice", "credit_note", "receipt", "unknown")


@dataclass
class ReviewLineInput:
    description: str = ""
    amount_excl: str = ""
    vat_code: str = ""
    vat_amount: str = ""
    account_code: str = ""  # 4-digit grootboekcode as shown in the select
    source_text: str = ""  # passage in the original document; carried through, never edited

    def is_blank(self) -> bool:
        return not any(
            v.strip()
            for v in (self.description, self.amount_excl, self.vat_code, self.vat_amount, self.account_code)
        )


@dataclass
class ReviewInput:
    """Everything as typed by the user (strings); `parse_review` makes it typed."""

    kind: str = "invoice"
    supplier_name: str = ""
    supplier_kvk: str = ""
    supplier_btw_number: str = ""
    supplier_iban: str = ""
    supplier_address_line: str = ""
    supplier_postal_code: str = ""
    supplier_city: str = ""
    supplier_country: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    currency: str = "EUR"
    total_excl: str = ""
    total_vat: str = ""
    total_incl: str = ""
    lines: list[ReviewLineInput] = field(default_factory=list)
    totals_override: bool = False  # "Het totaal klopt niet met de regels, ik weet het"
    exchange_rate: str = ""  # foreign units per euro, e.g. "1,0842"; only used when currency is not EUR
    shifted_vat_rate: str = ""  # Dutch btw rate (%) we compute on verlegde lines; blank = 21


@dataclass(frozen=True)
class ParsedLine:
    description: str | None
    amount_excl_cents: int | None
    vat_code: str | None
    vat_amount_cents: int | None
    account_code: str | None
    source_text: str | None = None


@dataclass(frozen=True)
class ParsedReview:
    kind: str
    supplier_name: str | None
    supplier_kvk: str | None
    supplier_btw_number: str | None
    supplier_iban: str | None
    supplier_address_line: str | None
    supplier_postal_code: str | None
    supplier_city: str | None
    supplier_country: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str
    total_excl_cents: int | None
    total_vat_cents: int | None
    total_incl_cents: int | None
    lines: tuple[ParsedLine, ...]
    totals_override: bool
    exchange_rate_micro: int | None = None
    shifted_vat_rate_bp: int | None = None


def _text(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    return value or None


def parse_date(text: str, label: str) -> date | None:
    """`dd-mm-jjjj` or ISO `jjjj-mm-dd`; blank gives None."""
    value = (text or "").strip()
    if not value:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"{label} '{value}' is geen geldige datum. Schrijf bijvoorbeeld 21-10-2026 (dd-mm-jjjj)."
    )


def parse_review(
    data: ReviewInput,
    *,
    accounts: Iterable[AccountRef],
    vat_codes: Mapping[str, int],
    finish: bool,
) -> ParsedReview:
    accounts = list(accounts)
    messages: list[str] = []
    fields: dict[str, str] = {}

    def problem(field_name: str, message: str) -> None:
        messages.append(message)
        fields.setdefault(field_name, message)

    def amount(raw: str, field_name: str, label: str) -> int | None:
        if not (raw or "").strip():
            return None
        try:
            return parse_euro(raw)
        except ValueError as exc:  # InvalidAmountError is a ValueError
            problem(field_name, f"{label}: {exc}")
            return None

    def date_of(raw: str, field_name: str, label: str) -> date | None:
        try:
            return parse_date(raw, label)
        except ValueError as exc:
            problem(field_name, str(exc))
            return None

    def identifier(validator, raw: str, field_name: str) -> str | None:
        try:
            return validator(_text(raw))
        except RelationError as exc:
            problem(field_name, exc.message)
            return None

    kind = (data.kind or "invoice").strip()
    if kind not in KINDS:
        problem("kind", f"'{kind}' is geen geldig soort document. Kies factuur, creditnota of bon.")
        kind = "invoice"

    currency = (data.currency or "").strip().upper() or "EUR"
    if len(currency) != 3 or not currency.isalpha():
        problem("currency", f"'{data.currency.strip()}' is geen geldige valuta. Schrijf bijvoorbeeld EUR.")
        currency = "EUR"

    exchange_rate_micro = None
    if currency != BASE_CURRENCY and (data.exchange_rate or "").strip():
        try:
            exchange_rate_micro = parse_rate(data.exchange_rate)
        except LedgerError as exc:
            problem("exchange_rate", exc.message)
    shifted_vat_rate_bp = None
    if (data.shifted_vat_rate or "").strip():
        try:
            shifted_vat_rate_bp = parse_rate_bp(data.shifted_vat_rate)
        except LedgerError as exc:
            problem("shifted_vat_rate", exc.message)

    parsed_lines: list[ParsedLine] = []
    position = 0
    for raw_line in data.lines:
        if raw_line.is_blank():
            continue
        n = position
        position += 1
        prefix = f"Regel {n + 1}"
        vat_code = _text(raw_line.vat_code)
        if vat_code is not None and vat_code not in vat_codes:
            problem(
                f"line.{n}.vat_code",
                f"{prefix}: BTW-tarief '{vat_code}' bestaat niet. Kies een tarief uit de lijst.",
            )
            vat_code = None
        account_code = _text(raw_line.account_code)
        if account_code is not None and resolve_account_code(account_code, accounts) is None:
            problem(
                f"line.{n}.account",
                f"{prefix}: rekening '{account_code}' kan hier niet worden gebruikt. "
                "Kies een kostenrekening uit de lijst.",
            )
            account_code = None
        parsed_lines.append(
            ParsedLine(
                description=_text(raw_line.description),
                amount_excl_cents=amount(raw_line.amount_excl, f"line.{n}.amount", f"{prefix}, bedrag zonder BTW"),
                vat_code=vat_code,
                vat_amount_cents=amount(raw_line.vat_amount, f"line.{n}.vat_amount", f"{prefix}, BTW-bedrag"),
                account_code=account_code,
                source_text=_text(raw_line.source_text),
            )
        )

    country = None
    if _text(data.supplier_country):
        country = identifier(validate_country, data.supplier_country, "supplier_country")

    parsed = ParsedReview(
        kind=kind,
        supplier_name=_text(data.supplier_name),
        supplier_kvk=identifier(validate_kvk, data.supplier_kvk, "supplier_kvk"),
        supplier_btw_number=identifier(validate_btw_number, data.supplier_btw_number, "supplier_btw_number"),
        supplier_iban=identifier(validate_iban, data.supplier_iban, "supplier_iban"),
        supplier_address_line=_text(data.supplier_address_line),
        supplier_postal_code=identifier(validate_postal_code, data.supplier_postal_code, "supplier_postal_code"),
        supplier_city=_text(data.supplier_city),
        supplier_country=country,
        invoice_number=_text(data.invoice_number),
        invoice_date=date_of(data.invoice_date, "invoice_date", "De factuurdatum"),
        due_date=date_of(data.due_date, "due_date", "De vervaldatum"),
        currency=currency,
        total_excl_cents=amount(data.total_excl, "total_excl", "Bedrag zonder BTW"),
        total_vat_cents=amount(data.total_vat, "total_vat", "BTW-bedrag"),
        total_incl_cents=amount(data.total_incl, "total_incl", "Totaal incl. BTW"),
        lines=tuple(parsed_lines),
        totals_override=bool(data.totals_override),
        exchange_rate_micro=exchange_rate_micro,
        shifted_vat_rate_bp=shifted_vat_rate_bp,
    )

    if finish:
        if currency != BASE_CURRENCY and exchange_rate_micro is None and "exchange_rate" not in fields:
            problem(
                "exchange_rate",
                f"Deze factuur is in {currency}. Vul de wisselkoers in (hoeveel {currency} je voor "
                "1 euro krijgt), anders kan ik de bedragen niet naar euro's omrekenen.",
            )
        if parsed.supplier_name is None:
            problem("supplier_name", "Vul de naam van de leverancier in.")
        if parsed.invoice_date is None and "invoice_date" not in fields:
            problem("invoice_date", "Vul de factuurdatum in.")
        amounts = [ln.amount_excl_cents for ln in parsed.lines if ln.amount_excl_cents is not None]
        if not amounts:
            problem("lines", "Vul minstens één regel met een bedrag in.")
        elif (
            parsed.total_excl_cents is not None
            and sum(amounts) != parsed.total_excl_cents
            and not parsed.totals_override
        ):
            problem(
                "total_excl",
                f"De regels tellen op tot {format_amount(sum(amounts), currency)}, maar het totaal is "
                f"{format_amount(parsed.total_excl_cents, currency)}. Pas een regel of het totaal aan.",
            )

    if messages:
        raise ReviewValidationError(messages, fields)
    return parsed
