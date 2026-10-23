"""Possible payments for an invoice that is still being reviewed (pure, no database).

An unprocessed bank transaction qualifies when it moves money the right way, does not
exceed the invoice and shows a sign of belonging to it: the exact amount, the invoice
number in the description or the supplier's IBAN. A name alone is too weak.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.bank.iban import normalize_iban
from app.domain.money import format_euro
from app.domain.reconcile.matching import _REASONS, _WEIGHT, _signals
from app.domain.reconcile.rules import normalize_text
from app.domain.reconcile.types import SIDE_CREDITOR, OpenItem, SOURCE_PURCHASE_INVOICE, TxnView, money_follows
from app.domain.relations.validation import normalize_name

PAID_EARLY_DAYS = 7  # a payment may land slightly before the invoice date (automatische incasso)


@dataclass(frozen=True)
class InvoiceView:
    """The fields of the invoice under review that the matching needs."""

    number: str | None
    invoice_date: date | None
    total_incl_cents: int | None
    is_credit: bool
    supplier_name: str | None
    supplier_iban: str | None


@dataclass(frozen=True)
class PaymentCandidate:
    txn: TxnView
    reasons: tuple[str, ...]
    score: int


def payment_candidates(invoice: InvoiceView, txns: Sequence[TxnView]) -> list[PaymentCandidate]:
    """Plausible payments, best first (most signals, then newest)."""
    total = invoice.total_incl_cents
    if not total or total <= 0:
        return []
    item = OpenItem(
        source=SOURCE_PURCHASE_INVOICE, source_id=0, contact_id=0, contact_name=invoice.supplier_name or "",
        iban=invoice.supplier_iban, number=invoice.number or "", date=invoice.invoice_date or date.min,
        due_date=None, open_cents=total, is_credit=invoice.is_credit, side=SIDE_CREDITOR,
    )
    earliest = invoice.invoice_date - timedelta(days=PAID_EARLY_DAYS) if invoice.invoice_date else None
    found = []
    for txn in txns:
        if not money_follows(txn.direction, SIDE_CREDITOR, invoice.is_credit) or txn.abs_cents > total:
            continue
        if earliest and txn.booking_date < earliest:
            continue
        signals = [
            s for s in _signals(
                txn, item, normalize_text(txn.description), normalize_iban(txn.counterparty_iban),
                normalize_name(txn.counterparty_name),
            )
            if s != "name"
        ]
        exact = txn.abs_cents == total
        if exact:
            signals.append("amount")
        if not signals:
            continue
        reasons = [_REASONS[s] for s in signals if s in _REASONS]
        if exact:
            reasons.append("Het bedrag klopt precies")
        else:
            reasons.append(f"Je betaalt een deel: {format_euro(txn.abs_cents)} van {format_euro(total)}")
        found.append(PaymentCandidate(txn, tuple(reasons), sum(_WEIGHT[s] for s in signals)))
    found.sort(key=lambda c: (-c.score, -c.txn.booking_date.toordinal(), c.txn.id))
    return found
