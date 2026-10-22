import hashlib
import stat

import pytest

from app.domain.bank.storage import BankFileStorage, storage_ext
from app.domain.errors import DocumentStorageFailedError

CONTENT = b"Datum;Bedrag\n20240301;1,00\n"


@pytest.fixture
def storage(tmp_path):
    return BankFileStorage(tmp_path / "bank")


def test_layout_and_content(storage, tmp_path):
    sha = hashlib.sha256(CONTENT).hexdigest()
    stored = storage.write(CONTENT, "csv")
    assert stored.path == tmp_path / "bank" / sha[:2] / f"{sha}.csv"
    assert stored.sha256 == sha and stored.size == len(CONTENT)
    assert stored.path.read_bytes() == CONTENT
    assert stat.S_IMODE(stored.path.stat().st_mode) == 0o444
    assert storage.exists(sha, "csv")
    with storage.open(sha, "csv") as f:
        assert f.read() == CONTENT


def test_same_bytes_reused_not_rewritten(storage):
    first = storage.write(CONTENT, "csv")
    mtime = first.path.stat().st_mtime_ns
    second = storage.write(CONTENT, "csv")
    assert second.path == first.path and second.path.stat().st_mtime_ns == mtime
    assert [p.name for p in first.path.parent.iterdir()] == [first.path.name]  # no temp leftovers


def test_never_overwrites_a_tampered_file(storage):
    stored = storage.write(CONTENT, "csv")
    stored.path.chmod(0o644)
    stored.path.write_bytes(b"tampered")
    with pytest.raises(DocumentStorageFailedError) as exc:
        storage.write(CONTENT, "csv")
    assert "data/bank" in exc.value.message
    assert stored.path.read_bytes() == b"tampered"


@pytest.mark.parametrize("ext", ["xml", "sta", "csv", "txt"])
def test_allowed_extensions(storage, ext):
    assert storage.write(b"x" + ext.encode(), ext).path.suffix == f".{ext}"


@pytest.mark.parametrize("ext", ["pdf", "exe", "../csv", ""])
def test_other_extensions_refused(storage, ext):
    with pytest.raises(ValueError):
        storage.write(CONTENT, ext)


def test_path_for_refuses_traversal(storage):
    with pytest.raises(ValueError):
        storage.path_for("../../etc/passwd", "csv")


def test_no_delete_api():
    assert not [n for n in dir(BankFileStorage) if n.startswith(("delete", "remove", "unlink"))]


def test_storage_ext():
    assert storage_ext("camt053", "x.xml") == "xml"
    assert storage_ext("mt940", "afschrift.sta") == "sta"
    assert storage_ext("mt940", "AFSCHRIFT.TXT") == "txt"
    assert storage_ext("csv", "x.tab") == "csv"
    with pytest.raises(ValueError):
        storage_ext("pdf")
