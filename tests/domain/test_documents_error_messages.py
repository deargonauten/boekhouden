"""Message lint for document errors: plain Dutch, no codes, always an actionable hint."""

import ast
import re
from pathlib import Path

import pytest

from app.domain import errors

ROOT = Path(__file__).resolve().parents[2] / "app" / "domain" / "documents"
FILES = [ROOT / "validation.py", ROOT / "status.py"]
OPTIONAL_FILES = [ROOT / "service.py", ROOT / "storage.py"]  # added by part B
DEV_ERRORS = {"ValueError", "TypeError", "KeyError", "RuntimeError", "IntegrityError", "OSError"}
FORBIDDEN_WORDS = re.compile(r"exception|traceback|none|invalid|error", re.IGNORECASE)
CODE_TOKEN = re.compile(r"[A-Z]{2,}_[A-Z_]+")
HINT = re.compile(
    r"controleer|kies|vul|open|gebruik|kort|probeer|ververs|geef|zoek|maak|zet|herstel", re.IGNORECASE
)

DOCUMENT_CLASSES = [
    ("UnsupportedFileTypeError", "UNSUPPORTED_FILE_TYPE"),
    ("FileTooLargeError", "FILE_TOO_LARGE"),
    ("EmptyFileError", "EMPTY_FILE"),
    ("NoFileSelectedError", "NO_FILE_SELECTED"),
    ("DocumentNotFoundError", "DOCUMENT_NOT_FOUND"),
    ("InvalidStatusTransitionError", "INVALID_STATUS_TRANSITION"),
    ("DocumentStorageFailedError", "DOCUMENT_STORAGE_FAILED"),
]


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{x}" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        return None if left is None or right is None else left + right
    return None


def _messages(path: Path):
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name.endswith("Error") and name not in DEV_ERRORS and node.args:
            msg = _literal(node.args[0])
            if msg is not None:
                found.append((node.lineno, msg))
    return found


def _lint(where: str, msg: str):
    assert not CODE_TOKEN.search(msg), where
    assert not FORBIDDEN_WORDS.search(msg), where
    assert msg.endswith((".", "?")), where
    assert HINT.search(msg), where


def test_messages_are_found():
    assert sum(len(_messages(p)) for p in FILES) >= 5


@pytest.mark.parametrize(
    "path", FILES + [p for p in OPTIONAL_FILES if p.exists()], ids=lambda p: p.name
)
def test_messages_are_plain_dutch(path):
    for lineno, msg in _messages(path):
        _lint(f"{path.name}:{lineno}: {msg!r}", msg)


@pytest.mark.parametrize("name,code", DOCUMENT_CLASSES)
def test_error_classes(name, code):
    cls = getattr(errors, name)
    assert issubclass(cls, errors.DocumentError)
    assert issubclass(cls, errors.LedgerError)
    assert cls.code == code
    assert getattr(errors, code) == code
    err = cls("Kies een ander bestand.")
    assert err.code == code
    assert err.message == "Kies een ander bestand."
    assert str(err) == "Kies een ander bestand."


def test_spec_messages_verbatim_in_source():
    """Messages that the spec fixes exactly and that live outside part A's files."""
    # NO_FILE_SELECTED, DOCUMENT_NOT_FOUND and DOCUMENT_STORAGE_FAILED are raised by
    # the route/service/storage; they are linted there. Lint the spec texts here.
    for msg in [
        "Je hebt nog geen bestand gekozen. Kies een PDF of foto van je factuur of bon.",
        "Het bestand kon niet worden opgeslagen. Controleer of er nog schijfruimte is en of de "
        "map data/documents beschrijfbaar is, en probeer het opnieuw.",
        "Het bestand ontbreekt op schijf. Herstel data/documents uit je back-up.",
    ]:
        _lint(repr(msg), msg)
