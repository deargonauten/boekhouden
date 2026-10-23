"""Email intake errors. Each carries a stable `code` and a plain-Dutch `message`."""

EMAIL_NOT_CONFIGURED = "EMAIL_NOT_CONFIGURED"
EMAIL_LOGIN_FAILED = "EMAIL_LOGIN_FAILED"
EMAIL_CONNECT_FAILED = "EMAIL_CONNECT_FAILED"
EMAIL_FOLDER_MISSING = "EMAIL_FOLDER_MISSING"
EMAIL_IMAP_ERROR = "EMAIL_IMAP_ERROR"


class EmailIntakeError(Exception):
    code: str = "EMAIL_INTAKE_ERROR"
    default_message: str = "De mailbox kon niet worden gelezen. Probeer het later opnieuw."

    def __init__(self, message: str | None = None):
        message = message or self.default_message
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class EmailNotConfiguredError(EmailIntakeError):
    code = EMAIL_NOT_CONFIGURED
    default_message = (
        "De mailbox is nog niet gekoppeld. Vul IMAP_HOST, IMAP_USER en IMAP_PASSWORD in "
        "je .env-bestand in en start het programma opnieuw."
    )


class EmailLoginFailedError(EmailIntakeError):
    code = EMAIL_LOGIN_FAILED
    default_message = (
        "Inloggen bij de mailbox is mislukt. Controleer gebruikersnaam en wachtwoord in je "
        ".env-bestand. Gebruikt je mailprovider app-wachtwoorden? Maak er dan een aan."
    )


class EmailConnectFailedError(EmailIntakeError):
    code = EMAIL_CONNECT_FAILED

    def __init__(self, host: str | None = None):
        super().__init__(
            f"Er kon geen verbinding worden gemaakt met {host or 'de mailserver'}. "
            "Controleer de servernaam, de poort en je internetverbinding."
        )


class EmailFolderMissingError(EmailIntakeError):
    code = EMAIL_FOLDER_MISSING

    def __init__(self, folder: str = "INBOX"):
        super().__init__(
            f"De map '{folder}' bestaat niet in de mailbox. Controleer IMAP_FOLDER in je .env-bestand."
        )


class EmailImapError(EmailIntakeError):
    code = EMAIL_IMAP_ERROR
    default_message = (
        "De mailserver gaf een onverwachte fout. Probeer het over een paar minuten opnieuw."
    )
