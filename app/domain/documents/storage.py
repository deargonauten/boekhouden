"""Content-addressed file storage for documents (bewaarplicht).

Layout: <root>/<sha256[0:2]>/<sha256>.<ext>. Files are written atomically,
made read-only and never overwritten. The only way to delete a stored file is
`DocumentStorage.remove`, used solely by `delete_document` for unbooked inbox
documents (never for booked ones). There is no way to truncate or overwrite.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.domain.errors import DocumentStorageFailedError

STORAGE_FAILED_MESSAGE = (
    "Het bestand kon niet worden opgeslagen. Controleer of er nog schijfruimte is "
    "en of de map data/documents beschrijfbaar is, en probeer het opnieuw."
)

DELETE_FAILED_MESSAGE = (
    "Het bestand kon niet worden verwijderd. Controleer of de map data/documents "
    "beschrijfbaar is en probeer het opnieuw."
)

DOCUMENT_EXTS = frozenset({"pdf", "jpg", "png", "webp"})
_SHA_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    ext: str
    size: int
    path: Path


def _failed() -> DocumentStorageFailedError:
    return DocumentStorageFailedError(STORAGE_FAILED_MESSAGE)


def _sha256_of_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


class DocumentStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, sha256: str, ext: str) -> Path:
        return self.root / sha256[:2] / f"{sha256}.{ext}"

    allowed_exts = DOCUMENT_EXTS

    def exists(self, sha256: str, ext: str) -> bool:
        return self.path_for(sha256, ext).is_file()

    def open(self, sha256: str, ext: str) -> BinaryIO:
        return self.path_for(sha256, ext).open("rb")

    def write(self, content: bytes, ext: str) -> StoredFile:
        sha = hashlib.sha256(content).hexdigest()
        final = self.path_for(sha, ext)
        stored = StoredFile(sha, ext, len(content), final)
        try:
            if final.exists():
                # Orphan of an earlier failed insert (or same bytes again): verify, reuse.
                if _sha256_of_file(final) != (sha, len(content)):
                    raise _failed()
                return stored
            final.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=final.parent, prefix=".tmp-")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(tmp, 0o444)
                try:
                    os.link(tmp, final)  # fails (never overwrites) if final appeared meanwhile
                except FileExistsError:
                    if _sha256_of_file(final) != (sha, len(content)):
                        raise _failed()
            finally:
                tmp.unlink(missing_ok=True)  # our own temp file only, never a stored document
        except DocumentStorageFailedError:
            raise
        except OSError as exc:
            raise _failed() from exc
        return stored

    def remove(self, sha256: str, ext: str) -> bool:
        """Delete exactly one stored file; True if a file was removed, False if absent.

        Only for `delete_document`. Raises ValueError for a malformed sha256/ext and lets
        OSError (e.g. permissions) propagate. An emptied shard directory is cleaned up.
        """
        if not _SHA_RE.fullmatch(sha256) or ext not in self.allowed_exts:
            raise ValueError("Ongeldige bestandsverwijzing")
        path = self.path_for(sha256, ext)
        root = self.root.resolve()
        if path.parent.resolve().parent != root:
            raise ValueError("Ongeldige bestandsverwijzing")
        if not path.is_file():
            return False
        os.chmod(path, 0o644)  # stored files are read-only
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        try:
            path.parent.rmdir()  # only succeeds when empty
        except OSError:
            pass
        return True
