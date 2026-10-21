"""Pure validation for uploaded documents: type sniffing, size, filenames."""

import re
import unicodedata
from dataclasses import dataclass

from app.domain.errors import (
    EmptyFileError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_FILENAME_LENGTH = 255

_PDF_WINDOW = 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_HEIC_BRANDS = {b"heic", b"heix", b"heif", b"mif1", b"hevc"}


@dataclass(frozen=True)
class DetectedType:
    content_type: str
    ext: str


PDF = DetectedType("application/pdf", "pdf")
JPEG = DetectedType("image/jpeg", "jpg")
PNG = DetectedType("image/png", "png")
WEBP = DetectedType("image/webp", "webp")
ALLOWED_TYPES: tuple[DetectedType, ...] = (PDF, JPEG, PNG, WEBP)


def format_size(size_bytes: int) -> str:
    """Human size with Dutch decimal comma: '1,2 MB', '340 KB', '12 bytes'."""
    if size_bytes >= 1024 * 1024:
        tenths = size_bytes * 10 // (1024 * 1024)  # truncate: never show more than there is
        return f"{tenths // 10},{tenths % 10} MB"
    if size_bytes >= 1024:
        return f"{size_bytes // 1024} KB"
    return f"{size_bytes} bytes"


def check_size(size_bytes: int) -> None:
    """Raise EmptyFileError for 0 bytes, FileTooLargeError above the limit."""
    if size_bytes <= 0:
        raise EmptyFileError("Dit bestand is leeg. Kies een ander bestand.")
    if size_bytes > MAX_DOCUMENT_BYTES:
        raise FileTooLargeError(
            f"Dit bestand is te groot ({format_size(size_bytes)}). De grens is 20 MB. "
            "Maak de PDF kleiner of fotografeer met een lagere resolutie."
        )


def sniff_type(data: bytes) -> DetectedType:
    """Detect the file type from its content (magic bytes), never from a name."""
    if data.find(b"%PDF-", 0, _PDF_WINDOW) != -1:
        return PDF
    if data[:3] == b"\xff\xd8\xff":
        return JPEG
    if data[:8] == _PNG_SIGNATURE:
        return PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        raise UnsupportedFileTypeError(
            "Dit lijkt een HEIC-foto (iPhone). Zet de foto om naar JPEG, of stel je camera in "
            "op 'Meest compatibel', en probeer het opnieuw."
        )
    raise UnsupportedFileTypeError(
        "Dit bestandstype kan niet worden verwerkt. Kies een PDF, JPEG, PNG of WebP-bestand."
    )


def validate_content(data: bytes) -> DetectedType:
    """Full check in the specified order: empty, too large, type."""
    check_size(len(data))
    return sniff_type(data)


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_filename(name: str | None, ext: str) -> str:
    """Safe display name: basename only, no control chars or separators, max 255 chars.

    Never use the result to build a filesystem path. Empty -> 'document.<ext>'.
    """
    cleaned = unicodedata.normalize("NFC", name or "")
    cleaned = _CONTROL.sub("", cleaned)
    cleaned = cleaned.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if cleaned in {".", ".."}:
        cleaned = ""
    if not cleaned:
        return f"document.{ext}"
    if len(cleaned) > MAX_FILENAME_LENGTH:
        stem, dot, suffix = cleaned.rpartition(".")
        if dot and 0 < len(suffix) <= 10:
            cleaned = stem[: MAX_FILENAME_LENGTH - len(suffix) - 1].rstrip() + "." + suffix
        else:
            cleaned = cleaned[:MAX_FILENAME_LENGTH].rstrip()
    return cleaned
