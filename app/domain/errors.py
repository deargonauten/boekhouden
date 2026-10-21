"""Domain errors. Each carries a stable `code` and a Dutch `message`."""

UNBALANCED = "UNBALANCED"
TOO_FEW_LINES = "TOO_FEW_LINES"
INVALID_LINE_AMOUNT = "INVALID_LINE_AMOUNT"
ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
NO_OPEN_PERIOD = "NO_OPEN_PERIOD"
PERIOD_LOCKED = "PERIOD_LOCKED"
ALREADY_REVERSED = "ALREADY_REVERSED"
CANNOT_REVERSE_STORNO = "CANNOT_REVERSE_STORNO"
INVALID_VAT_CODE = "INVALID_VAT_CODE"
YEAR_EXISTS = "YEAR_EXISTS"
YEAR_NOT_FOUND = "YEAR_NOT_FOUND"
ACCOUNT_IN_USE = "ACCOUNT_IN_USE"
# Additional codes used by the pure domain layer.
INVALID_AMOUNT = "INVALID_AMOUNT"
INVALID_DESCRIPTION = "INVALID_DESCRIPTION"
INVALID_DATE = "INVALID_DATE"
INVALID_KIND = "INVALID_KIND"


class LedgerError(Exception):
    """Base error. `code` is stable (for routes/tests), `message` is Dutch."""

    code: str = "LEDGER_ERROR"

    def __init__(self, code_or_message: str, message: str | None = None):
        # LedgerError(code, message) or Subclass(message)
        if message is None:
            code, message = type(self).code, code_or_message
        else:
            code = code_or_message
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def _error_class(name: str, code: str, *bases: type) -> type[LedgerError]:
    return type(name, (LedgerError, *bases), {"code": code})


UnbalancedError = _error_class("UnbalancedError", UNBALANCED)
TooFewLinesError = _error_class("TooFewLinesError", TOO_FEW_LINES)
InvalidLineAmountError = _error_class("InvalidLineAmountError", INVALID_LINE_AMOUNT)
AccountInactiveError = _error_class("AccountInactiveError", ACCOUNT_INACTIVE)
AccountNotFoundError = _error_class("AccountNotFoundError", ACCOUNT_NOT_FOUND)
NoOpenPeriodError = _error_class("NoOpenPeriodError", NO_OPEN_PERIOD)
PeriodLockedError = _error_class("PeriodLockedError", PERIOD_LOCKED)
AlreadyReversedError = _error_class("AlreadyReversedError", ALREADY_REVERSED)
CannotReverseStornoError = _error_class("CannotReverseStornoError", CANNOT_REVERSE_STORNO)
InvalidVatCodeError = _error_class("InvalidVatCodeError", INVALID_VAT_CODE)
YearExistsError = _error_class("YearExistsError", YEAR_EXISTS)
YearNotFoundError = _error_class("YearNotFoundError", YEAR_NOT_FOUND)
AccountInUseError = _error_class("AccountInUseError", ACCOUNT_IN_USE)
# Amount parsing failures are also ValueErrors.
InvalidAmountError = _error_class("InvalidAmountError", INVALID_AMOUNT, ValueError)
InvalidDescriptionError = _error_class("InvalidDescriptionError", INVALID_DESCRIPTION)
InvalidDateError = _error_class("InvalidDateError", INVALID_DATE)
InvalidKindError = _error_class("InvalidKindError", INVALID_KIND)
