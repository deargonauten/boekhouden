"""Mailbox access over IMAP (TLS only). The rest of the app only sees `MailboxClient`.

Nothing here ever deletes: handled mails are moved (or copied and marked read), never
flagged \\Deleted and never expunged.
"""

import base64
import imaplib
import logging
import re
import socket
import ssl
from contextlib import contextmanager
from typing import Iterator, Protocol

from app.config import Settings
from app.domain.email_intake.errors import (
    EmailConnectFailedError,
    EmailFolderMissingError,
    EmailImapError,
    EmailIntakeError,
    EmailLoginFailedError,
    EmailNotConfiguredError,
)

logger = logging.getLogger("app.email_intake")

_SIZE_BATCH = 200


class MailboxClient(Protocol):
    def connect(self) -> None: ...

    def list_unseen(self) -> list[tuple[str, int]]:
        """(uid, size in bytes) of unread mails, oldest first."""

    def fetch(self, uid: str) -> bytes: ...

    def mark_processed(self, uid: str) -> None: ...

    def close(self) -> None: ...


def encode_modified_utf7(name: str) -> str:
    """IMAP folder names: modified UTF-7 (RFC 3501 5.1.3)."""
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            raw = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _folder_arg(name: str) -> str:
    return _quote(encode_modified_utf7(name))


class ImapMailbox:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        folder: str,
        processed_folder: str,
        timeout: int = 30,
    ):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._folder = folder
        self._processed_folder = processed_folder
        self._timeout = timeout
        self._conn: imaplib.IMAP4_SSL | None = None
        self._processed_ready = False

    def _log_safe(self, exc: BaseException) -> str:
        text = f"{type(exc).__name__}: {exc}"
        return text.replace(self._password, "***") if self._password else text

    @contextmanager
    def _mapped(self) -> Iterator[None]:
        """Turn imaplib/socket errors into plain-Dutch EmailIntakeErrors."""
        try:
            yield
        except EmailIntakeError:
            raise
        except (OSError, ssl.SSLError, EOFError) as exc:  # includes socket.timeout
            logger.warning("imap connection problem: %s", self._log_safe(exc))
            raise EmailConnectFailedError(self._host) from None
        except imaplib.IMAP4.error as exc:
            logger.warning("imap error: %s", self._log_safe(exc))
            raise EmailImapError() from None

    def connect(self) -> None:
        with self._mapped():
            try:
                self._conn = imaplib.IMAP4_SSL(
                    self._host,
                    self._port,
                    ssl_context=ssl.create_default_context(),
                    timeout=self._timeout,
                )
            except (OSError, ssl.SSLError, socket.timeout, EOFError) as exc:
                logger.warning("imap connect failed: %s", self._log_safe(exc))
                raise EmailConnectFailedError(self._host) from None
            try:
                self._conn.login(self._user, self._password)
            except imaplib.IMAP4.error as exc:
                logger.warning("imap login rejected: %s", self._log_safe(exc))
                raise EmailLoginFailedError() from None
            typ, data = self._conn.select(_folder_arg(self._folder), readonly=False)
            if typ != "OK":
                logger.warning("imap select failed: %r", data)
                raise EmailFolderMissingError(self._folder)

    def _need_conn(self) -> imaplib.IMAP4_SSL:
        if self._conn is None:
            raise EmailImapError()
        return self._conn

    def list_unseen(self) -> list[tuple[str, int]]:
        conn = self._need_conn()
        with self._mapped():
            typ, data = conn.uid("SEARCH", "UNSEEN")
            if typ != "OK":
                raise EmailImapError()
            raw = data[0] if data and data[0] else b""
            uids = sorted(raw.decode("ascii", "ignore").split(), key=int)
            sizes: dict[str, int] = {}
            for start in range(0, len(uids), _SIZE_BATCH):
                batch = uids[start : start + _SIZE_BATCH]
                typ, data = conn.uid("FETCH", ",".join(batch), "(RFC822.SIZE)")
                if typ != "OK":
                    raise EmailImapError()
                for item in data or []:
                    line = item[0] if isinstance(item, tuple) else item
                    if not isinstance(line, (bytes, bytearray)):
                        continue
                    text = bytes(line).decode("ascii", "ignore")
                    uid_m = re.search(r"UID (\d+)", text)
                    size_m = re.search(r"RFC822\.SIZE (\d+)", text)
                    if uid_m and size_m:
                        sizes[uid_m.group(1)] = int(size_m.group(1))
            return [(uid, sizes.get(uid, 0)) for uid in uids]

    def fetch(self, uid: str) -> bytes:
        conn = self._need_conn()
        with self._mapped():
            typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK":
                raise EmailImapError()
            for item in data or []:
                if isinstance(item, tuple) and isinstance(item[1], (bytes, bytearray)):
                    return bytes(item[1])
            raise EmailImapError()

    def _ensure_processed_folder(self, conn: imaplib.IMAP4_SSL) -> None:
        if self._processed_ready:
            return
        # CREATE answers NO when the folder exists already; that is fine.
        conn.create(_folder_arg(self._processed_folder))
        self._processed_ready = True

    def _has_move(self, conn: imaplib.IMAP4_SSL) -> bool:
        caps = getattr(conn, "capabilities", ()) or ()
        return any(str(c).upper() == "MOVE" for c in caps)

    def mark_processed(self, uid: str) -> None:
        conn = self._need_conn()
        with self._mapped():
            self._ensure_processed_folder(conn)
            target = _folder_arg(self._processed_folder)
            if self._has_move(conn):
                typ, _ = conn.uid("MOVE", uid, target)
                if typ != "OK":
                    raise EmailImapError()
                return
            typ, _ = conn.uid("COPY", uid, target)
            if typ != "OK":
                raise EmailImapError()
            typ, _ = conn.uid("STORE", uid, "+FLAGS.SILENT", "(\\Seen)")
            if typ != "OK":
                raise EmailImapError()

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.logout()  # never CLOSE: that would expunge mails someone else flagged \\Deleted
        except Exception:
            pass


def build_mailbox(settings: Settings) -> ImapMailbox:
    if not settings.imap_configured:
        raise EmailNotConfiguredError()
    return ImapMailbox(
        host=settings.imap_host,
        port=settings.imap_port,
        user=settings.imap_user,
        password=settings.imap_password.get_secret_value(),
        folder=settings.imap_folder,
        processed_folder=settings.imap_processed_folder,
        timeout=settings.imap_timeout_seconds,
    )
