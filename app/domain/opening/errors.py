"""Errors of the beginbalans. Each carries a stable `code` and a Dutch `message`."""

from app.domain.errors import LedgerError

NO_FISCAL_YEAR = "NO_FISCAL_YEAR"
NOT_FIRST_YEAR = "NOT_FIRST_YEAR"
NO_JOURNAL = "NO_JOURNAL"
ACCOUNT_NOT_ALLOWED = "ACCOUNT_NOT_ALLOWED"
EMPTY = "EMPTY"
INVALID_ITEM = "INVALID_ITEM"
DUPLICATE_ITEM = "DUPLICATE_ITEM"
ITEM_PAID = "ITEM_PAID"
UNCHANGED = "UNCHANGED"
SYSTEM_ACCOUNT_MISSING = "SYSTEM_ACCOUNT_MISSING"

NO_FISCAL_YEAR_MESSAGE = "Maak eerst je eerste boekjaar aan onder Instellingen > Boekjaren."
NO_JOURNAL_MESSAGE = (
    "Er is geen memoriaal actief. Zet het memoriaal aan onder Instellingen > Dagboeken."
)
EMPTY_MESSAGE = "Vul minstens één bedrag of openstaande factuur in."
UNCHANGED_MESSAGE = "Er is niets veranderd."
NEGATIVE_EQUITY_WARNING = (
    "Je schulden zijn hoger dan je bezittingen; je eigen vermogen is negatief. Klopt dat?"
)


class OpeningError(LedgerError):
    """The beginbalans cannot be booked (as entered)."""

    code = "OPENING_ERROR"


def not_first_year_message(year: int, first_year: int) -> str:
    return (
        f"De beginbalans van {year} volgt uit het boekjaar ervoor. "
        f"Alleen je eerste boekjaar ({first_year}) krijgt een beginbalans."
    )


def account_not_allowed_message(code: str | None, name: str | None) -> str:
    label = f"Rekening {code} {name}" if code else "Deze rekening"
    return f"{label} hoort niet in de beginbalans. Kies een rekening voor bezittingen of schulden."


def item_paid_message(invoice_number: str) -> str:
    return (
        f"Factuur {invoice_number} uit je beginbalans is al (deels) betaald. "
        "Pas de beginbalans aan met een gewone boeking in het memoriaal."
    )


def duplicate_item_message(invoice_number: str, relation_name: str) -> str:
    return f"Factuur {invoice_number} van {relation_name} staat er twee keer in."
