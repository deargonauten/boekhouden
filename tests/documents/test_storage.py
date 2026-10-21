import hashlib
import os
import stat

import pytest

from app.domain.documents.storage import DocumentStorage
from app.domain.errors import DocumentStorageFailedError

from tests.documents.conftest import PDF


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_path_layout(storage, test_settings):
    h = sha(PDF)
    assert storage.path_for(h, "pdf") == test_settings.documents_dir / h[:2] / f"{h}.pdf"


def test_write_stores_content_readonly(storage):
    stored = storage.write(PDF, "pdf")
    assert stored.sha256 == sha(PDF)
    assert stored.size == len(PDF)
    assert stored.path.read_bytes() == PDF
    assert stat.S_IMODE(stored.path.stat().st_mode) == 0o444
    assert storage.exists(stored.sha256, "pdf")


def test_write_leaves_no_temp_files(storage, test_settings):
    stored = storage.write(PDF, "pdf")
    assert [p.name for p in stored.path.parent.iterdir()] == [stored.path.name]


def test_write_identical_existing_file_is_reused(storage):
    first = storage.write(PDF, "pdf")
    mtime = first.path.stat().st_mtime_ns
    second = storage.write(PDF, "pdf")
    assert second.path == first.path
    assert first.path.stat().st_mtime_ns == mtime


def test_existing_file_with_wrong_content_is_not_overwritten(storage):
    h = sha(PDF)
    path = storage.path_for(h, "pdf")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupt")
    with pytest.raises(DocumentStorageFailedError):
        storage.write(PDF, "pdf")
    assert path.read_bytes() == b"corrupt"


def test_open_reads_back(storage):
    stored = storage.write(PDF, "pdf")
    with storage.open(stored.sha256, "pdf") as f:
        assert f.read() == PDF


def test_no_delete_api(storage):
    for name in ("delete", "remove", "unlink", "purge"):
        assert not hasattr(storage, name)
        assert not hasattr(DocumentStorage, name)


def test_unwritable_root_raises_storage_failed(tmp_path):
    root = tmp_path / "ro"
    root.mkdir()
    os.chmod(root, 0o555)
    try:
        if os.access(root, os.W_OK):
            pytest.skip("running as a user that ignores directory permissions")
        with pytest.raises(DocumentStorageFailedError) as exc:
            DocumentStorage(root).write(PDF, "pdf")
        assert "data/documents" in exc.value.message
    finally:
        os.chmod(root, 0o755)


def test_root_created_when_missing(tmp_path):
    root = tmp_path / "new" / "documents"
    stored = DocumentStorage(root).write(PDF, "pdf")
    assert stored.path.exists()
