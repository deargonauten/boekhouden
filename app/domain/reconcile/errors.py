"""Errors of the bank reconciliation. Each has a stable `code` and a plain Dutch `message`."""

from app.domain.errors import LedgerError
from app.domain.money import format_euro

NOT_FOUND = "RECONCILE_NOT_FOUND"
ALREADY_PROCESSED = "RECONCILE_ALREADY_PROCESSED"
NOT_BOOKED = "RECONCILE_NOT_BOOKED"
NOT_IGNORED = "RECONCILE_NOT_IGNORED"
IGNORED = "RECONCILE_IGNORED"
NOTHING_TO_BOOK = "RECONCILE_NOTHING_TO_BOOK"
NOT_DISTRIBUTED = "RECONCILE_NOT_DISTRIBUTED"
OVER_DISTRIBUTED = "RECONCILE_OVER_DISTRIBUTED"
OVER_ALLOCATED = "RECONCILE_OVER_ALLOCATED"
INVALID_AMOUNT = "RECONCILE_INVALID_AMOUNT"
WRONG_DIRECTION = "RECONCILE_WRONG_DIRECTION"
ITEM_NOT_FOUND = "RECONCILE_ITEM_NOT_FOUND"
DUPLICATE_ITEM = "RECONCILE_DUPLICATE_ITEM"
ACCOUNT_REQUIRED = "RECONCILE_ACCOUNT_REQUIRED"
VAT_REQUIRED = "RECONCILE_VAT_REQUIRED"
UNSUPPORTED_VAT = "RECONCILE_UNSUPPORTED_VAT"
VAT_ON_INCOMING = "RECONCILE_VAT_ON_INCOMING"
SUGGESTION_GONE = "RECONCILE_SUGGESTION_GONE"
RULE_INVALID = "RECONCILE_RULE_INVALID"
RULE_NOT_FOUND = "RECONCILE_RULE_NOT_FOUND"
SYSTEM_ACCOUNT_MISSING = "RECONCILE_SYSTEM_ACCOUNT_MISSING"
MIXED_SIDES = "RECONCILE_MIXED_SIDES"

ALREADY_PROCESSED_MESSAGE = "Deze mutatie is al verwerkt."
UNSUPPORTED_VAT_MESSAGE = (
    "Verlegde of buitenlandse BTW boeken we hier nog niet automatisch; "
    "leg dit vast met een handmatige boeking."
)
VAT_ON_INCOMING_MESSAGE = (
    "Geld dat bij komt kun je hier alleen zonder BTW boeken. Omzet met BTW boek je straks "
    "via een verkoopfactuur."
)
WRONG_DIRECTION_AF_MESSAGE = (
    "Een bedrag af kun je alleen koppelen aan inkoopfacturen; kies een creditnota alleen bij "
    "een bedrag dat bij komt."
)
WRONG_DIRECTION_BIJ_MESSAGE = (
    "Een bedrag dat bij komt kun je alleen koppelen aan een creditnota; een inkoopfactuur "
    "betaal je met een bedrag dat af gaat."
)
WRONG_DIRECTION_DEBTOR_BIJ_MESSAGE = (
    "Een bedrag dat bij komt kun je alleen koppelen aan verkoopfacturen; een verkoopcreditnota "
    "betaal je terug met een bedrag dat af gaat."
)
WRONG_DIRECTION_DEBTOR_AF_MESSAGE = (
    "Een bedrag dat af gaat kun je alleen koppelen aan een verkoopcreditnota (terugbetaling aan "
    "een klant); een verkoopfactuur betaalt je klant met een bedrag dat bij komt."
)
MIXED_SIDES_MESSAGE = (
    "Je kunt een betaling niet tegelijk aan verkoop- en inkoopfacturen koppelen. Koppel ze apart."
)


class ReconcileError(LedgerError):
    """A bank transaction cannot be reconciled. `message` is plain Dutch, safe to show."""

    code = "RECONCILE_ERROR"


def not_distributed(remainder_cents: int) -> ReconcileError:
    return ReconcileError(NOT_DISTRIBUTED, f"Er is nog {format_euro(remainder_cents)} niet verdeeld.")


def over_distributed(excess_cents: int) -> ReconcileError:
    return ReconcileError(
        OVER_DISTRIBUTED,
        f"Je hebt {format_euro(excess_cents)} meer verdeeld dan het bedrag van deze mutatie. "
        "Verlaag een bedrag.",
    )


def over_allocated(open_cents: int) -> ReconcileError:
    amount = format_euro(open_cents)
    return ReconcileError(
        OVER_ALLOCATED,
        f"Je kunt maximaal {amount} aan deze factuur toewijzen; er staat nog {amount} open.",
    )
