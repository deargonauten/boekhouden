"""Errors of the inkoopfactuur booking. Each carries a stable `code`, a Dutch `message`
and, when the fix is on the review screen, the review form `field` to link to."""

from app.domain.errors import LedgerError

NOT_REVIEWED = "NOT_REVIEWED"
MISSING_FIELD = "MISSING_FIELD"
ZERO_AMOUNT = "ZERO_AMOUNT"
INVALID_TOTALS = "INVALID_TOTALS"
UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"
UNSUPPORTED_VAT = "UNSUPPORTED_VAT"
DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
ALREADY_BOOKED = "ALREADY_BOOKED"
NO_JOURNAL = "NO_JOURNAL"
SYSTEM_ACCOUNT_MISSING = "SYSTEM_ACCOUNT_MISSING"

ALREADY_BOOKED_MESSAGE = "Dit document is al geboekt."
NOT_REVIEWED_MESSAGE = (
    "Deze factuur is nog niet nagekeken. Kijk de gegevens eerst na en klik op "
    "'Klaar met nakijken'; daarna kun je hem boeken."
)
UNSUPPORTED_VAT_MESSAGE = (
    "Deze factuur heeft verlegde of buitenlandse BTW. Dat boeken we hier nog niet "
    "automatisch; leg het vast met een handmatige boeking."
)
NO_JOURNAL_MESSAGE = (
    "Er is geen inkoopdagboek actief. Zet het inkoopdagboek (IK) weer aan onder "
    "Instellingen > Dagboeken."
)


class BookingError(LedgerError):
    """A purchase invoice cannot be booked (yet). `field` names the review form field, if any."""

    code = "BOOKING_ERROR"

    def __init__(self, code_or_message: str, message: str | None = None, *, field: str | None = None):
        super().__init__(code_or_message, message)
        self.field = field


def duplicate_message(supplier_name: str, invoice_number: str) -> str:
    return f"Deze factuur van {supplier_name} met nummer {invoice_number} is al geboekt."
