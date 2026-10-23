import imaplib
import logging
import socket
import ssl

import pytest

from app.config import Settings
from app.domain.email_intake import mailbox as mb
from app.domain.email_intake import (
    EmailConnectFailedError,
    EmailFolderMissingError,
    EmailImapError,
    EmailLoginFailedError,
    EmailNotConfiguredError,
    ImapMailbox,
    build_mailbox,
    test_connection,
)

PASSWORD = "s3cret-pw-XYZ"


class FakeImap:
    """Stands in for imaplib.IMAP4_SSL; records every command."""

    instances: list["FakeImap"] = []
    capabilities = ("IMAP4REV1", "MOVE")
    login_error = False
    connect_error: Exception | None = None
    select_ok = True
    command_ok = True

    def __init__(self, host, port, ssl_context=None, timeout=None):
        if type(self).connect_error:
            raise type(self).connect_error
        self.host, self.port, self.ssl_context, self.timeout = host, port, ssl_context, timeout
        self.calls: list[tuple] = []
        type(self).instances.append(self)

    def login(self, user, password):
        self.calls.append(("LOGIN", user))
        if type(self).login_error:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] bad " + password)
        return "OK", [b"ok"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("SELECT", mailbox, readonly))
        return ("OK", [b"3"]) if type(self).select_ok else ("NO", [b"nope"])

    def create(self, mailbox):
        self.calls.append(("CREATE", mailbox))
        return "NO", [b"[ALREADYEXISTS]"]

    def uid(self, command, *args):
        self.calls.append(("UID", command, *args))
        if not type(self).command_ok:
            return "NO", [b"fail"]
        if command == "SEARCH":
            return "OK", [b"12 3 7"]
        if command == "FETCH" and args[1] == "(RFC822.SIZE)":
            return "OK", [b"1 (UID 3 RFC822.SIZE 100)", b"2 (UID 7 RFC822.SIZE 200)", b"3 (UID 12 RFC822.SIZE 300)"]
        if command == "FETCH":
            return "OK", [(b"1 (UID 3 BODY[] {5}", b"hello"), b")"]
        return "OK", [b"done"]

    def logout(self):
        self.calls.append(("LOGOUT",))
        return "BYE", [b""]

    def close(self):  # would EXPUNGE; must never be used
        self.calls.append(("CLOSE",))


@pytest.fixture(autouse=True)
def fake_imap(monkeypatch):
    FakeImap.instances = []
    FakeImap.capabilities = ("IMAP4REV1", "MOVE")
    FakeImap.login_error = False
    FakeImap.connect_error = None
    FakeImap.select_ok = True
    FakeImap.command_ok = True
    monkeypatch.setattr(mb.imaplib, "IMAP4_SSL", FakeImap)


def box(folder="INBOX"):
    return ImapMailbox("imap.example.com", 993, "user@example.com", PASSWORD, folder, "Verwerkt", 7)


def commands(conn):
    return [c[0] if c[0] != "UID" else "UID " + c[1] for c in conn.calls]


def test_connect_uses_verified_tls_and_timeout():
    b = box()
    b.connect()
    conn = FakeImap.instances[0]
    assert (conn.host, conn.port, conn.timeout) == ("imap.example.com", 993, 7)
    assert conn.ssl_context.verify_mode == ssl.CERT_REQUIRED and conn.ssl_context.check_hostname
    assert ("SELECT", '"INBOX"', False) in conn.calls
    b.close()


def test_list_unseen_oldest_first_with_sizes():
    b = box()
    b.connect()
    assert b.list_unseen() == [("3", 100), ("7", 200), ("12", 300)]


def test_fetch_uses_peek():
    b = box()
    b.connect()
    assert b.fetch("3") == b"hello"
    conn = FakeImap.instances[0]
    assert ("UID", "FETCH", "3", "(BODY.PEEK[])") in conn.calls
    assert not any("BODY[]" in str(c) for c in conn.calls)


def test_mark_processed_moves_when_supported_and_creates_folder():
    b = box()
    b.connect()
    b.mark_processed("3")
    conn = FakeImap.instances[0]
    assert ("CREATE", '"Verwerkt"') in conn.calls
    assert ("UID", "MOVE", "3", '"Verwerkt"') in conn.calls
    assert not any(c[:2] == ("UID", "COPY") for c in conn.calls)


def test_mark_processed_falls_back_to_copy_and_seen():
    FakeImap.capabilities = ("IMAP4REV1",)
    b = box()
    b.connect()
    b.mark_processed("3")
    conn = FakeImap.instances[0]
    assert ("UID", "COPY", "3", '"Verwerkt"') in conn.calls
    assert ("UID", "STORE", "3", "+FLAGS.SILENT", "(\\Seen)") in conn.calls


def test_never_deletes_or_expunges():
    FakeImap.capabilities = ("IMAP4REV1",)
    b = box()
    b.connect()
    b.list_unseen()
    b.fetch("3")
    b.mark_processed("3")
    b.close()
    text = str(FakeImap.instances[0].calls).upper()
    assert "EXPUNGE" not in text and "DELETED" not in text and "CLOSE" not in text
    assert commands(FakeImap.instances[0])[-1] == "LOGOUT"


def test_mark_failure_maps_to_imap_error():
    b = box()
    b.connect()
    FakeImap.command_ok = False
    with pytest.raises(EmailImapError):
        b.mark_processed("3")


def test_non_ascii_folder_is_modified_utf7():
    assert mb.encode_modified_utf7("Verwerkt") == "Verwerkt"
    assert mb.encode_modified_utf7("Facturen & co") == "Facturen &- co"
    assert mb.encode_modified_utf7("Café") == "Caf&AOk-"
    b = box("Café")
    b.connect()
    assert ("SELECT", '"Caf&AOk-"', False) in FakeImap.instances[0].calls


def test_login_failure_message_and_no_password_leak(caplog):
    FakeImap.login_error = True
    with caplog.at_level(logging.DEBUG, logger="app.email_intake"):
        with pytest.raises(EmailLoginFailedError) as e:
            box().connect()
    assert e.value.code == "EMAIL_LOGIN_FAILED"
    assert e.value.message == (
        "Inloggen bij de mailbox is mislukt. Controleer gebruikersnaam en wachtwoord in je "
        ".env-bestand. Gebruikt je mailprovider app-wachtwoorden? Maak er dan een aan."
    )
    assert PASSWORD not in caplog.text and PASSWORD not in str(e.value)


@pytest.mark.parametrize("exc", [socket.timeout("t"), socket.gaierror("dns"), ssl.SSLError("tls"), ConnectionRefusedError()])
def test_connect_failures(exc):
    FakeImap.connect_error = exc
    with pytest.raises(EmailConnectFailedError) as e:
        box().connect()
    assert e.value.code == "EMAIL_CONNECT_FAILED"
    assert e.value.message == (
        "Er kon geen verbinding worden gemaakt met imap.example.com. "
        "Controleer de servernaam, de poort en je internetverbinding."
    )


def test_missing_folder():
    FakeImap.select_ok = False
    with pytest.raises(EmailFolderMissingError) as e:
        box("Nope").connect()
    assert e.value.code == "EMAIL_FOLDER_MISSING"
    assert e.value.message == "De map 'Nope' bestaat niet in de mailbox. Controleer IMAP_FOLDER in je .env-bestand."


def test_other_imap_error():
    b = box()
    b.connect()
    FakeImap.command_ok = False
    with pytest.raises(EmailImapError) as e:
        b.list_unseen()
    assert e.value.code == "EMAIL_IMAP_ERROR"
    assert e.value.message == "De mailserver gaf een onverwachte fout. Probeer het over een paar minuten opnieuw."


def test_timeout_during_fetch_is_connect_error():
    b = box()
    b.connect()
    b._conn.uid = lambda *a: (_ for _ in ()).throw(socket.timeout("slow"))
    with pytest.raises(EmailConnectFailedError):
        b.fetch("3")


def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_build_mailbox_not_configured():
    with pytest.raises(EmailNotConfiguredError) as e:
        build_mailbox(settings())
    assert e.value.code == "EMAIL_NOT_CONFIGURED"
    assert e.value.message == (
        "De mailbox is nog niet gekoppeld. Vul IMAP_HOST, IMAP_USER en IMAP_PASSWORD in "
        "je .env-bestand in en start het programma opnieuw."
    )


def test_test_connection_counts_unread_and_closes():
    s = settings(imap_host="imap.example.com", imap_user="u", imap_password=PASSWORD)
    result = test_connection(s)
    assert (result.unread_count, result.folder) == (3, "INBOX")
    cmds = commands(FakeImap.instances[0])
    assert cmds[-1] == "LOGOUT" and "UID MOVE" not in cmds and "UID STORE" not in cmds


def test_test_connection_closes_on_error():
    FakeImap.select_ok = False
    s = settings(imap_host="h", imap_user="u", imap_password=PASSWORD)
    with pytest.raises(EmailFolderMissingError):
        test_connection(s)
    assert commands(FakeImap.instances[0])[-1] == "LOGOUT"
