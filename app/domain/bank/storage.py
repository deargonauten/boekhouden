"""Content-addressed storage for original bank files (bewaarplicht).

Same guarantees as DocumentStorage (atomic write, read-only, never overwritten, no
delete API: `remove` is disabled) but in its own root (`data/bank/`) with its own allowed extensions.
Layout: <root>/<sha256[0:2]>/<sha256>.<ext>
"""

import re
from pathlib import Path

from app.domain.documents.storage import DocumentStorage, StoredFile
from app.domain.errors import DocumentStorageFailedError

ALLOWED_EXTS = frozenset({"xml", "sta", "csv", "txt"})

BANK_STORAGE_FAILED_MESSAGE = (
    "Het bankbestand kon niet worden opgeslagen. Controleer of er nog schijfruimte is "
    "en of de map data/bank beschrijfbaar is, en probeer het opnieuw."
)

_SHA_RE = re.compile(r"[0-9a-f]{64}")


def storage_ext(detected_format: str, filename: str = "") -> str:
    """File extension to store a detected format under: camt053 -> xml, mt940 -> sta/txt, csv -> csv."""
    if detected_format == "camt053":
        return "xml"
    if detected_format == "mt940":
        return "txt" if filename.lower().endswith(".txt") else "sta"
    if detected_format == "csv":
        return "csv"
    raise ValueError(f"Onbekend bestandsformaat: {detected_format}")


class BankFileStorage(DocumentStorage):
    def __init__(self, root: Path):
        super().__init__(root)

    def path_for(self, sha256: str, ext: str) -> Path:
        if not _SHA_RE.fullmatch(sha256) or ext not in ALLOWED_EXTS:
            raise ValueError("Ongeldige bestandsverwijzing")
        return super().path_for(sha256, ext)

    def remove(self, sha256: str, ext: str) -> bool:
        raise DocumentStorageFailedError("Bankbestanden worden nooit verwijderd (bewaarplicht).")

    def write(self, content: bytes, ext: str) -> StoredFile:
        if ext not in ALLOWED_EXTS:
            raise ValueError(f"Bestandstype .{ext} is niet toegestaan voor bankbestanden")
        try:
            return super().write(content, ext)
        except DocumentStorageFailedError as exc:
            raise DocumentStorageFailedError(BANK_STORAGE_FAILED_MESSAGE) from exc
