"""Mail builders and a FakeMailbox for email intake tests."""

from email.message import EmailMessage as Mail

import pytest
from sqlalchemy.orm import Session

from tests.documents.conftest import JPEG, PDF, PNG, WEBP, storage  # noqa: F401
from tests.ledger.conftest import engine, session  # noqa: F401

PDF2 = PDF + b"%second\n"
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20
BIG_JPEG = JPEG + b"\x00" * 40_000


def make_mail(subject="Factuur 1", message_id="<m1@example.com>", attachments=(), body="Zie bijlage"):
    msg = Mail()
    msg["From"] = "Leverancier <lev@example.com>"
    msg["To"] = "facturen@example.org"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 05 Oct 2026 10:00:00 +0200"
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(body)
    for filename, data, *rest in attachments:
        mime = rest[0] if rest else "application/pdf"
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


def raw(msg) -> bytes:
    return msg.as_bytes()


class FakeMailbox:
    def __init__(self, mails=None):
        # uid -> raw bytes, insertion order = oldest first
        self.mails: dict[str, bytes] = dict(mails or {})
        self.processed: list[str] = []
        self.fetched: list[str] = []
        self.closed = 0
        self.connected = 0
        self.fail_fetch: set[str] = set()
        self.fail_mark: set[str] = set()
        self.sizes: dict[str, int] = {}
        self.connect_error: Exception | None = None

    def connect(self):
        self.connected += 1
        if self.connect_error:
            raise self.connect_error

    def list_unseen(self):
        return [(u, self.sizes.get(u, len(r))) for u, r in self.mails.items() if u not in self.processed]

    def fetch(self, uid):
        self.fetched.append(uid)
        if uid in self.fail_fetch:
            raise RuntimeError("boom")
        return self.mails[uid]

    def mark_processed(self, uid):
        from app.domain.email_intake import EmailImapError

        if uid in self.fail_mark:
            raise EmailImapError()
        self.processed.append(uid)

    def close(self):
        self.closed += 1


@pytest.fixture
def session_factory(engine):  # noqa: F811
    return lambda: Session(engine, expire_on_commit=False)
