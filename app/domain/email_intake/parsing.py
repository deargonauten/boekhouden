"""Pure mail parsing: find invoice attachments (also in forwarded mails) and header info.

No IMAP, no database. Never raises on corrupt MIME structure.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from app.domain.documents import validation
from app.domain.errors import UnsupportedFileTypeError

logger = logging.getLogger("app.email_intake")

MAX_NESTING_DEPTH = 5
MAX_CANDIDATES = 50
INLINE_IMAGE_MAX_BYTES = 30 * 1024
MAX_TEXT_LENGTH = 200

REASON_UNSUPPORTED = "Bestandstype wordt niet ondersteund (alleen PDF en foto's)"
REASON_HEIC = "Foto's in HEIC-formaat worden niet ondersteund; stuur JPEG of PNG"
REASON_EMPTY = "Het bestand is leeg"
REASON_TOO_LARGE = "Het bestand is groter dan 20 MB"
REASON_TOO_DEEP = "Doorgestuurde mails zitten te diep in elkaar"
REASON_TOO_MANY = "Er zijn al 50 bijlagen in deze mail gevonden; de rest is overgeslagen"
REASON_UNREADABLE_MAIL = "De bijgevoegde mail kon niet worden gelezen"
REASON_UNREADABLE = "Deze mail kon niet worden gelezen"

_IMAGE_EXTS = {"jpg", "png", "webp"}
_MAIL_HEADERS = ("from", "subject", "message-id", "date", "to")


@dataclass(frozen=True)
class Candidate:
    filename: str
    content: bytes
    origin: str  # "bijlage" or "doorgestuurd"


@dataclass(frozen=True)
class SkippedPart:
    filename: str
    reason: str


@dataclass
class ExtractionResult:
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[SkippedPart] = field(default_factory=list)


@dataclass(frozen=True)
class MailInfo:
    message_key: str
    from_addr: str
    subject: str
    received_at: datetime


def _parse(raw: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(raw)


def _clip(value: object) -> str:
    return " ".join(str(value or "").split())[:MAX_TEXT_LENGTH]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _header(msg: Message, name: str) -> str:
    try:
        return str(msg[name] or "")
    except Exception:  # malformed header values
        return ""


def read_mail_info(raw: bytes) -> MailInfo:
    try:
        msg = _parse(raw)
    except Exception:
        logger.warning("mail headers could not be parsed", exc_info=True)
        msg = Message()
    message_id = _header(msg, "Message-ID").strip().strip("<>").strip().lower()
    key = message_id or "sha256:" + hashlib.sha256(raw).hexdigest()
    received = _now()
    date_header = _header(msg, "Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            received = parsed
        except (TypeError, ValueError, IndexError):
            pass
    return MailInfo(
        message_key=key,
        from_addr=_clip(_header(msg, "From")),
        subject=_clip(_header(msg, "Subject")),
        received_at=received,
    )


class _State:
    def __init__(self) -> None:
        self.result = ExtractionResult()
        self.seen: set[str] = set()


def _filename(part: Message) -> str | None:
    try:
        name = part.get_filename()
    except Exception:
        return None
    return str(name) if name else None


def _looks_like_mail(msg: Message) -> bool:
    return any(msg.get(h) is not None for h in _MAIL_HEADERS)


def _skip(state: _State, filename: str, reason: str) -> None:
    state.result.skipped.append(SkippedPart(filename, reason))


def _handle_leaf(part: Message, depth: int, state: _State) -> None:
    ctype = part.get_content_type()
    name = _filename(part)
    is_eml = bool(name and name.lower().endswith(".eml"))
    if not is_eml and (ctype.startswith("text/") or "signature" in ctype):
        return
    try:
        data = part.get_payload(decode=True)
    except Exception:
        data = None
    if not isinstance(data, (bytes, bytearray)):
        return
    data = bytes(data)

    if is_eml:
        try:
            nested = _parse(data)
            ok = _looks_like_mail(nested)
        except Exception:
            ok = False
        if not ok:
            _skip(state, name, REASON_UNREADABLE_MAIL)
            return
        _walk(nested, depth + 1, state)
        return

    disposition = part.get_content_disposition()
    has_cid = part.get("Content-ID") is not None
    inline = disposition == "inline" or (has_cid and disposition != "attachment")
    if not data:
        _skip(state, name or "bijlage", REASON_EMPTY)
        return
    try:
        detected = validation.sniff_type(data)
    except UnsupportedFileTypeError as exc:
        if inline and (not name or len(data) < INLINE_IMAGE_MAX_BYTES):
            return  # gif/svg logos and tracking pixels
        _skip(state, name or "bijlage", REASON_HEIC if "HEIC" in exc.message else REASON_UNSUPPORTED)
        return

    if inline and detected.ext in _IMAGE_EXTS and len(data) < INLINE_IMAGE_MAX_BYTES:
        return
    display = name or f"bijlage.{detected.ext}"
    if len(data) > validation.MAX_DOCUMENT_BYTES:
        _skip(state, display, REASON_TOO_LARGE)
        return
    digest = hashlib.sha256(data).hexdigest()
    if digest in state.seen:
        return
    if len(state.result.candidates) >= MAX_CANDIDATES:
        _skip(state, display, REASON_TOO_MANY)
        return
    state.seen.add(digest)
    state.result.candidates.append(
        Candidate(display, data, "bijlage" if depth == 0 else "doorgestuurd")
    )


def _walk(msg: Message, depth: int, state: _State) -> None:
    if depth > MAX_NESTING_DEPTH:
        _skip(state, "doorgestuurde mail", REASON_TOO_DEEP)
        return
    if msg.get_content_type() == "message/rfc822":
        payload = msg.get_payload()
        nested = payload[0] if isinstance(payload, list) and payload else None
        if isinstance(nested, Message):
            _walk(nested, depth + 1, state)
        else:
            _skip(state, _filename(msg) or "doorgestuurde mail", REASON_UNREADABLE_MAIL)
        return
    if msg.is_multipart():
        for sub in msg.iter_parts():
            try:
                _walk(sub, depth, state)
            except Exception:
                logger.warning("mail part could not be read", exc_info=True)
                _skip(state, _filename(sub) or "bijlage", REASON_UNREADABLE_MAIL)
        return
    _handle_leaf(msg, depth, state)


def extract_attachments(raw_message: bytes) -> ExtractionResult:
    state = _State()
    try:
        _walk(_parse(raw_message), 0, state)
    except Exception:
        logger.warning("mail could not be parsed", exc_info=True)
        if not state.result.candidates and not state.result.skipped:
            _skip(state, "mail", REASON_UNREADABLE)
    return state.result
