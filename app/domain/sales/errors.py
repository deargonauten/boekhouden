"""Errors of the verkoopfacturen. Each carries a stable `code`, a Dutch `message` and, when the
fix is on a form, the `field` to link to ("company", "contact", "invoice_date", "due_date",
"lines", "line-<n>-<name>", "note", ...)."""

from app.domain.errors import LedgerError

NOT_FINALIZABLE = "NOT_FINALIZABLE"
MISSING_FIELD = "MISSING_FIELD"
DATE_ORDER = "DATE_ORDER"
IMMUTABLE = "IMMUTABLE"
UNSUPPORTED_VAT = "UNSUPPORTED_VAT"
OVER_CREDIT = "OVER_CREDIT"
INVALID_INPUT = "INVALID_INPUT"
NO_JOURNAL = "NO_JOURNAL"
SYSTEM_ACCOUNT_MISSING = "SYSTEM_ACCOUNT_MISSING"
PDF_FAILED = "PDF_FAILED"
NOT_FOUND = "SALES_NOT_FOUND"
CREDIT_NOT_ALLOWED = "CREDIT_NOT_ALLOWED"
CREDIT_LINES_FIXED = "CREDIT_LINES_FIXED"
REMINDER_NOT_ALLOWED = "REMINDER_NOT_ALLOWED"

IMMUTABLE_MESSAGE = (
    "Deze factuur is definitief en kan niet meer worden gewijzigd. "
    "Maak een creditnota om iets te corrigeren."
)
NO_JOURNAL_MESSAGE = "Er is geen verkoopdagboek actief. Maak er een aan onder Instellingen."
PDF_FAILED_MESSAGE = "De PDF kon niet worden gemaakt, er is niets vastgelegd. Probeer het opnieuw."
ZERO_TOTAL_MESSAGE = "Het totaal is €0,00; zo'n factuur kun je niet boeken."
CREDIT_LINES_FIXED_MESSAGE = (
    "Een creditnota corrigeert alleen de oorspronkelijke factuur. "
    "Wil je iets anders aanrekenen, maak dan een nieuwe factuur."
)
UNSUPPORTED_VAT_MESSAGE = (
    "Dit BTW-tarief kan nog niet op een verkoopfactuur. Kies 21%, 9% of 0%. "
    "Verlegde BTW, levering aan het buitenland en KOR volgen later."
)
STORNO_WARNING = "Corrigeren doe je met een creditnota, niet met een stornoboeking."


class SalesError(LedgerError):
    """A verkoopfactuur cannot be saved or made definitief (yet)."""

    code = "SALES_ERROR"

    def __init__(self, code_or_message: str, message: str | None = None, *, field: str | None = None):
        super().__init__(code_or_message, message)
        self.field = field


def date_order_message(latest) -> str:
    d = f"{latest:%d-%m-%Y}"
    return (
        f"Er is al een factuur met datum {d}. Een factuur mag geen eerdere datum hebben dan de "
        f"vorige, anders klopt de nummering niet. Kies {d} of later."
    )


def over_credit_message(max_milli: int, already_milli: int) -> str:
    from app.domain.sales.amounts import format_quantity

    return (
        f"Je kunt maximaal {format_quantity(max_milli)} van deze regel crediteren; "
        f"er is al {format_quantity(already_milli)} gecrediteerd."
    )
