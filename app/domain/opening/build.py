"""Pure beginbalans rules (no DB): input shapes, validation, summary and the journal entry.

Sign rules: an asset amount > 0 is a debit, a liability amount > 0 a credit (negative
amounts the other way round). Debiteur posten debit 1300, crediteur posten credit 3000.
Eigen vermogen (2000) is whatever balances the entry, so it always balances.
"""

from dataclasses import dataclass, field
from datetime import date

from app.domain.ledger.entries import NewEntry, NewLine
from app.domain.money import require_cents
from app.domain.opening.errors import (
    ACCOUNT_NOT_ALLOWED,
    DUPLICATE_ITEM,
    EMPTY,
    EMPTY_MESSAGE,
    INVALID_ITEM,
    NEGATIVE_EQUITY_WARNING,
    OpeningError,
    account_not_allowed_message,
    duplicate_item_message,
)

DEBITEUR = "debiteur"
CREDITEUR = "crediteur"
SIDES = (DEBITEUR, CREDITEUR)
SIDE_LABELS = {DEBITEUR: "klanten", CREDITEUR: "leveranciers"}
MAX_INVOICE_NUMBER_LENGTH = 64


@dataclass(frozen=True)
class OpeningItemInput:
    """One openstaande factuur: a klant that owes you (debiteur) or a leverancier you owe."""

    side: str  # 'debiteur' | 'crediteur'
    contact_id: int | None
    invoice_number: str
    invoice_date: date | None
    due_date: date | None
    amount_cents: int


@dataclass(frozen=True)
class OpeningInput:
    balances: list[tuple[int, int]] = field(default_factory=list)  # (account_id, amount_cents)
    items: list[OpeningItemInput] = field(default_factory=list)


@dataclass(frozen=True)
class AccountRef:
    id: int
    code: str
    name: str
    type: str  # 'asset' | 'liability' (equity etc. only as labels for messages)


@dataclass(frozen=True)
class OpeningSummary:
    assets_cents: int  # totaal bezittingen
    liabilities_cents: int  # totaal schulden
    equity_cents: int  # eigen vermogen (berekend) = bezittingen - schulden
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SystemIds:
    debtors: int  # 1300 Debiteuren
    creditors: int  # 3000 Crediteuren
    equity: int  # 2000 Ondernemingsvermogen / Kapitaal


def invoice_number_key(number: str) -> str:
    """Normalised invoice number for the duplicate guard (trimmed, lower case)."""
    return number.strip().lower()


def merged_balances(balances: list[tuple[int, int]]) -> dict[int, int]:
    """Non-zero amount per account (several rows for one account are added up)."""
    out: dict[int, int] = {}
    for account_id, cents in balances:
        out[account_id] = out.get(account_id, 0) + require_cents(cents)
    return {a: c for a, c in out.items() if c}


def row_labels(items: list[OpeningItemInput]) -> list[str]:
    """'Openstaande factuur 2 (leveranciers)': numbered per side, as on the form."""
    counters = {side: 0 for side in SIDES}
    labels = []
    for item in items:
        side = item.side if item.side in SIDES else DEBITEUR
        counters[side] += 1
        labels.append(f"Openstaande factuur {counters[side]} ({SIDE_LABELS[side]})")
    return labels


def _item_problem(item: OpeningItemInput, start_date: date) -> str | None:
    if item.side not in SIDES:
        return "Kies of dit een factuur van een klant of van een leverancier is."
    if item.contact_id is None:
        return "Kies bij welke relatie deze factuur hoort."
    number = (item.invoice_number or "").strip()
    if not number:
        return "Vul het factuurnummer in."
    if len(number) > MAX_INVOICE_NUMBER_LENGTH:
        return f"Het factuurnummer is te lang (maximaal {MAX_INVOICE_NUMBER_LENGTH} tekens)."
    if item.invoice_date is None:
        return "Vul de factuurdatum in."
    if item.invoice_date > start_date:
        return (
            "De factuurdatum ligt na de startdatum van je administratie. "
            "Boek deze factuur gewoon via de Inbox of Verkoop."
        )
    if item.due_date is not None and item.due_date < item.invoice_date:
        return "De vervaldatum ligt vóór de factuurdatum. Controleer beide datums."
    if require_cents(item.amount_cents) <= 0:
        return (
            "Vul een bedrag groter dan nul in. Een openstaande creditnota trek je af van "
            "een andere factuur van dezelfde relatie."
        )
    return None


def item_error(label: str, problem: str) -> OpeningError:
    return OpeningError(INVALID_ITEM, f"{label}: {problem}")


def check_input(
    data: OpeningInput,
    allowed: dict[int, AccountRef],
    start_date: date,
    *,
    contact_names: dict[int, str] | None = None,
    account_labels: dict[int, AccountRef] | None = None,
) -> None:
    """Raise OpeningError for the first problem. Contact existence is checked by the service.

    `contact_names` and `account_labels` only make the messages more specific.
    """
    balances = merged_balances(data.balances)
    for account_id in balances:
        if account_id not in allowed:
            ref = (account_labels or {}).get(account_id)
            raise OpeningError(
                ACCOUNT_NOT_ALLOWED,
                account_not_allowed_message(ref.code if ref else None, ref.name if ref else None),
            )
    if not balances and not data.items:
        raise OpeningError(EMPTY, EMPTY_MESSAGE)
    seen: set[tuple[str, int, str]] = set()
    for label, item in zip(row_labels(data.items), data.items):
        problem = _item_problem(item, start_date)
        if problem:
            raise item_error(label, problem)
        key = (item.side, item.contact_id, invoice_number_key(item.invoice_number))
        if key in seen:
            name = (contact_names or {}).get(item.contact_id, "deze relatie")
            raise OpeningError(
                DUPLICATE_ITEM, duplicate_item_message(item.invoice_number.strip(), name)
            )
        seen.add(key)


def summarize(data: OpeningInput, allowed: dict[int, AccountRef]) -> OpeningSummary:
    """Totals for the form; skips rows that are incomplete or not allowed (never raises)."""
    assets = liabilities = 0
    for account_id, cents in data.balances:
        ref = allowed.get(account_id)
        if ref is None or not isinstance(cents, int) or isinstance(cents, bool):
            continue
        if ref.type == "asset":
            assets += cents
        elif ref.type == "liability":
            liabilities += cents
    for item in data.items:
        cents = item.amount_cents
        if not isinstance(cents, int) or isinstance(cents, bool) or cents <= 0:
            continue
        if item.side == DEBITEUR:
            assets += cents
        elif item.side == CREDITEUR:
            liabilities += cents
    equity = assets - liabilities
    warnings = [NEGATIVE_EQUITY_WARNING] if equity < 0 else []
    return OpeningSummary(assets, liabilities, equity, warnings)


def _signed_line(account_id: int, cents: int, debit_positive: bool) -> NewLine:
    debit = cents if debit_positive else -cents
    if debit > 0:
        return NewLine(account_id, debit_cents=debit)
    return NewLine(account_id, credit_cents=-debit)


def build_entry(
    data: OpeningInput,
    allowed: dict[int, AccountRef],
    system: SystemIds,
    journal_id: int,
    year: int,
    start_date: date,
    contact_names: dict[int, str],
) -> NewEntry:
    """The opening entry for already-checked input (see `check_input`)."""
    balances = merged_balances(data.balances)
    lines = [
        _signed_line(account_id, cents, allowed[account_id].type == "asset")
        for account_id, cents in sorted(balances.items(), key=lambda kv: allowed[kv[0]].code)
    ]
    for side, account_id in ((DEBITEUR, system.debtors), (CREDITEUR, system.creditors)):
        for item in data.items:
            if item.side != side:
                continue
            description = f"{contact_names.get(item.contact_id, '')} - {item.invoice_number.strip()}"
            line = _signed_line(account_id, item.amount_cents, side == DEBITEUR)
            line.description = description
            lines.append(line)
    equity = sum(l.debit_cents for l in lines) - sum(l.credit_cents for l in lines)
    if equity:
        lines.append(_signed_line(system.equity, equity, False))
    return NewEntry(
        journal_id=journal_id,
        booking_date=start_date,
        description=f"Beginbalans {year}",
        lines=lines,
        reference=None,
        kind="opening",
    )
