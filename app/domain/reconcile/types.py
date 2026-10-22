"""Plain data types of the bank reconciliation (afletteren). No database, no logic."""

from dataclasses import dataclass
from datetime import date

SOURCE_PURCHASE_INVOICE = "purchase_invoice"
SOURCE_OPENING_ITEM = "opening_item"
SOURCES = (SOURCE_PURCHASE_INVOICE, SOURCE_OPENING_ITEM)

CONFIDENCE_ZEKER = "zeker"
CONFIDENCE_WAARSCHIJNLIJK = "waarschijnlijk"

KIND_MATCH = "match"
KIND_RULE = "rule"


@dataclass(frozen=True)
class OpenItem:
    """Something that still has to be paid (or refunded): an inkoopfactuur, creditnota or
    openstaande post of the beginbalans. `open_cents` is always the positive amount that is
    left; a creditnota is flagged with `is_credit`."""

    source: str  # 'purchase_invoice' | 'opening_item'
    source_id: int
    contact_id: int
    contact_name: str
    iban: str | None
    number: str
    date: date
    due_date: date | None
    open_cents: int
    is_credit: bool = False
    side: str = "crediteur"

    @property
    def ref(self) -> tuple[str, int]:
        return (self.source, self.source_id)


@dataclass(frozen=True)
class Allocation:
    """Part of a bank transaction assigned to one open item. `amount_cents` > 0."""

    source: str
    source_id: int
    amount_cents: int


@dataclass(frozen=True)
class AllocationLine:
    """An Allocation together with what the entry builder needs to know about the item."""

    source: str
    source_id: int
    amount_cents: int
    is_credit: bool
    number: str
    open_cents: int


@dataclass(frozen=True)
class DirectLine:
    """Booking without invoice: `amount_cents` is incl. btw and > 0."""

    account_id: int | None
    amount_cents: int
    vat_code: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TxnView:
    """The fields of a bank transaction the matching needs. `amount_cents` is signed
    (negative = af, positive = bij)."""

    id: int
    booking_date: date
    amount_cents: int
    counterparty_name: str | None
    counterparty_iban: str | None
    description: str
    bank_reference: str | None = None

    @property
    def direction(self) -> str:
        return "af" if self.amount_cents < 0 else "bij"

    @property
    def abs_cents(self) -> int:
        return abs(self.amount_cents)


@dataclass(frozen=True)
class RuleView:
    id: int
    name: str
    counterparty_iban: str | None
    description_contains: str | None
    direction: str  # 'af' | 'bij' | 'beide'
    account_id: int
    vat_code: str | None
    contact_id: int | None
    use_count: int = 0


@dataclass(frozen=True)
class RuleDraft:
    """'Onthoud dit voor volgende keer': what to remember about a direct booking. Account and
    btw-code come from the first direct line; direction from the transaction."""

    use_iban: bool = True
    description_contains: str | None = None
    name: str | None = None
    contact_id: int | None = None


@dataclass(frozen=True)
class Suggestion:
    kind: str  # 'match' | 'rule'
    allocations: tuple[Allocation, ...]
    rule_id: int | None
    direct_lines: tuple[DirectLine, ...]
    confidence: str  # 'zeker' | 'waarschijnlijk'
    reasons: tuple[str, ...]
    contact_id: int | None
    label: str = ""  # plain Dutch summary, e.g. "Bol B.V. - F-1, F-2" or the rule name
    score: int = 0

    @property
    def key(self) -> str:
        """Stable identifier that `accept` uses to find this suggestion again server-side."""
        if self.kind == KIND_RULE:
            return f"rule:{self.rule_id}"
        return "match:" + "+".join(f"{a.source}-{a.source_id}-{a.amount_cents}" for a in self.allocations)
