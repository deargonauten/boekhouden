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


# --- Relaties (klanten en leveranciers) -------------------------------------
INVALID_KVK = "INVALID_KVK"
INVALID_BTW_NUMBER = "INVALID_BTW_NUMBER"
INVALID_IBAN = "INVALID_IBAN"
INVALID_EMAIL = "INVALID_EMAIL"
INVALID_NAME = "INVALID_NAME"
INVALID_POSTAL_CODE = "INVALID_POSTAL_CODE"
INVALID_COUNTRY = "INVALID_COUNTRY"
NAME_REQUIRED = "NAME_REQUIRED"
ROLE_REQUIRED = "ROLE_REQUIRED"
DUPLICATE_KVK = "DUPLICATE_KVK"
DUPLICATE_BTW_NUMBER = "DUPLICATE_BTW_NUMBER"
DUPLICATE_IBAN = "DUPLICATE_IBAN"
CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"


class RelationError(LedgerError):
    """Base for relation errors.

    A form with several problems raises ONE RelationError that carries all of
    them: `errors` holds the individual errors, `messages` their Dutch texts,
    `codes` their codes. `code`/`message` are those of the first one;
    `str()` joins all messages.
    """

    code = "RELATION_ERROR"

    def __init__(
        self,
        code_or_message: str,
        message: str | None = None,
        *,
        errors: "list[RelationError] | None" = None,
    ):
        super().__init__(code_or_message, message)
        self.errors: list[RelationError] = list(errors) if errors else [self]

    @classmethod
    def combine(cls, errors: "list[RelationError]") -> "RelationError":
        """One error for several; returns the error itself when there is one."""
        if len(errors) == 1:
            return errors[0]
        first = errors[0]
        return cls(first.code, first.message, errors=errors)

    @property
    def messages(self) -> list[str]:
        return [e.message for e in self.errors]

    @property
    def codes(self) -> list[str]:
        return [e.code for e in self.errors]

    @property
    def is_duplicate(self) -> bool:
        return any(c.startswith("DUPLICATE_") for c in self.codes)

    def __str__(self) -> str:
        return " ".join(self.messages)


def _relation_error(name: str, code: str) -> type[RelationError]:
    return type(name, (RelationError,), {"code": code})


InvalidKvkError = _relation_error("InvalidKvkError", INVALID_KVK)
InvalidBtwNumberError = _relation_error("InvalidBtwNumberError", INVALID_BTW_NUMBER)
InvalidIbanError = _relation_error("InvalidIbanError", INVALID_IBAN)
InvalidEmailError = _relation_error("InvalidEmailError", INVALID_EMAIL)
InvalidNameError = _relation_error("InvalidNameError", INVALID_NAME)
InvalidPostalCodeError = _relation_error("InvalidPostalCodeError", INVALID_POSTAL_CODE)
InvalidCountryError = _relation_error("InvalidCountryError", INVALID_COUNTRY)
NameRequiredError = _relation_error("NameRequiredError", NAME_REQUIRED)
RoleRequiredError = _relation_error("RoleRequiredError", ROLE_REQUIRED)
DuplicateKvkError = _relation_error("DuplicateKvkError", DUPLICATE_KVK)
DuplicateBtwNumberError = _relation_error("DuplicateBtwNumberError", DUPLICATE_BTW_NUMBER)
DuplicateIbanError = _relation_error("DuplicateIbanError", DUPLICATE_IBAN)
ContactNotFoundError = _relation_error("ContactNotFoundError", CONTACT_NOT_FOUND)


# --- Documenten (inbox) ------------------------------------------------------
UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
EMPTY_FILE = "EMPTY_FILE"
NO_FILE_SELECTED = "NO_FILE_SELECTED"
DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
DOCUMENT_STORAGE_FAILED = "DOCUMENT_STORAGE_FAILED"
DOCUMENT_DELETE_NOT_ALLOWED = "DOCUMENT_DELETE_NOT_ALLOWED"


class DocumentError(LedgerError):
    """Base for document (inbox) errors."""

    code = "DOCUMENT_ERROR"


def _document_error(name: str, code: str) -> type[DocumentError]:
    return type(name, (DocumentError,), {"code": code})


UnsupportedFileTypeError = _document_error("UnsupportedFileTypeError", UNSUPPORTED_FILE_TYPE)
FileTooLargeError = _document_error("FileTooLargeError", FILE_TOO_LARGE)
EmptyFileError = _document_error("EmptyFileError", EMPTY_FILE)
NoFileSelectedError = _document_error("NoFileSelectedError", NO_FILE_SELECTED)
DocumentNotFoundError = _document_error("DocumentNotFoundError", DOCUMENT_NOT_FOUND)
InvalidStatusTransitionError = _document_error(
    "InvalidStatusTransitionError", INVALID_STATUS_TRANSITION
)
DocumentStorageFailedError = _document_error("DocumentStorageFailedError", DOCUMENT_STORAGE_FAILED)
DocumentDeleteNotAllowedError = _document_error(
    "DocumentDeleteNotAllowedError", DOCUMENT_DELETE_NOT_ALLOWED
)


# --- AI-factuurherkenning (uitlezen) ----------------------------------------
EXTRACTOR_UNAVAILABLE = "EXTRACTOR_UNAVAILABLE"
EXTRACTION_RATE_LIMITED = "EXTRACTION_RATE_LIMITED"
EXTRACTION_TIMEOUT = "EXTRACTION_TIMEOUT"
EXTRACTION_FAILED = "EXTRACTION_FAILED"
EXTRACTION_NOT_ALLOWED = "EXTRACTION_NOT_ALLOWED"
EXTRACTION_NOT_FOUND = "EXTRACTION_NOT_FOUND"
REVIEW_INVALID = "REVIEW_INVALID"

UNAVAILABLE_MESSAGE = (
    "Het uitlezen kan nog niet: je bent niet ingelogd bij Claude. "
    "Open Terminal en typ: claude auth login. "
    "Of zet ANTHROPIC_API_KEY in het bestand .env."
)
RATE_LIMITED_MESSAGE = (
    "Je Claude-limiet is bereikt. Probeer het over een uur nog eens, "
    "of zet ANTHROPIC_API_KEY in .env om per factuur te betalen."
)
FAILED_MESSAGE = "Het uitlezen is niet gelukt. Probeer het opnieuw of vul de gegevens zelf in."
NOT_ALLOWED_MESSAGE = "Dit document is al geboekt en kan niet opnieuw worden uitgelezen."
NOT_FOUND_MESSAGE = "Voor dit document is nog niets uitgelezen. Klik op 'Lees factuur uit'."


def timeout_message(seconds: int) -> str:
    return (
        f"Het uitlezen duurde te lang (meer dan {seconds} seconden). "
        "Probeer het opnieuw; lukt het niet, vul de factuur dan zelf in."
    )


class ExtractionError(LedgerError):
    """Base for extraction errors. Technical detail goes to the log, never the UI."""

    code = "EXTRACTION_ERROR"


def _extraction_error(name: str, code: str) -> type[ExtractionError]:
    return type(name, (ExtractionError,), {"code": code})


ExtractorUnavailableError = _extraction_error("ExtractorUnavailableError", EXTRACTOR_UNAVAILABLE)
ExtractionRateLimitedError = _extraction_error(
    "ExtractionRateLimitedError", EXTRACTION_RATE_LIMITED
)
ExtractionTimeoutError = _extraction_error("ExtractionTimeoutError", EXTRACTION_TIMEOUT)
ExtractionFailedError = _extraction_error("ExtractionFailedError", EXTRACTION_FAILED)
ExtractionNotAllowedError = _extraction_error("ExtractionNotAllowedError", EXTRACTION_NOT_ALLOWED)
ExtractionNotFoundError = _extraction_error("ExtractionNotFoundError", EXTRACTION_NOT_FOUND)


class ReviewValidationError(ExtractionError):
    """The nakijken form has problems; `messages` lists every one in Dutch."""

    code = REVIEW_INVALID

    def __init__(self, messages: list[str], fields: dict[str, str] | None = None):
        self.messages: list[str] = list(messages)
        # form field name (e.g. "invoice_date", "line-0-amount") -> message, for inline display
        self.fields: dict[str, str] = dict(fields or {})
        super().__init__(self.code, " ".join(self.messages))


# --- Bedrijfsgegevens --------------------------------------------------------
INVALID_COMPANY_KVK = "INVALID_COMPANY_KVK"
INVALID_COMPANY_BTW_ID = "INVALID_COMPANY_BTW_ID"
INVALID_COMPANY_IBAN = "INVALID_COMPANY_IBAN"
INVALID_COMPANY_POSTAL_CODE = "INVALID_COMPANY_POSTAL_CODE"
INVALID_COMPANY_LEGAL_FORM = "INVALID_COMPANY_LEGAL_FORM"
COMPANY_NAME_REQUIRED = "COMPANY_NAME_REQUIRED"
COMPANY_NAME_TOO_LONG = "COMPANY_NAME_TOO_LONG"
COMPANY_INCOMPLETE = "COMPANY_INCOMPLETE"


class CompanyError(RelationError):
    """Base for bedrijfsgegevens errors; one error can carry many messages (see RelationError)."""

    code = "COMPANY_ERROR"


def _company_error(name: str, code: str) -> type[CompanyError]:
    return type(name, (CompanyError,), {"code": code})


InvalidCompanyKvkError = _company_error("InvalidCompanyKvkError", INVALID_COMPANY_KVK)
InvalidCompanyBtwIdError = _company_error("InvalidCompanyBtwIdError", INVALID_COMPANY_BTW_ID)
InvalidCompanyIbanError = _company_error("InvalidCompanyIbanError", INVALID_COMPANY_IBAN)
InvalidCompanyPostalCodeError = _company_error(
    "InvalidCompanyPostalCodeError", INVALID_COMPANY_POSTAL_CODE
)
InvalidCompanyLegalFormError = _company_error(
    "InvalidCompanyLegalFormError", INVALID_COMPANY_LEGAL_FORM
)
CompanyNameRequiredError = _company_error("CompanyNameRequiredError", COMPANY_NAME_REQUIRED)
CompanyNameTooLongError = _company_error("CompanyNameTooLongError", COMPANY_NAME_TOO_LONG)
CompanyIncompleteError = _company_error("CompanyIncompleteError", COMPANY_INCOMPLETE)


# --- Btw-codes (grootboek-verfijning) ----------------------------------------
# INVALID_VAT_CODE is defined above and reused for a bad code or missing name.
DUPLICATE_CODE = "DUPLICATE_CODE"
INVALID_VAT_RATE = "INVALID_VAT_RATE"
INVALID_RUBRIEK = "INVALID_RUBRIEK"
VAT_CODE_IN_LOCKED_PERIOD = "VAT_CODE_IN_LOCKED_PERIOD"
VAT_CODE_IS_DEFAULT = "VAT_CODE_IS_DEFAULT"
VAT_CODE_SYSTEM = "VAT_CODE_SYSTEM"
