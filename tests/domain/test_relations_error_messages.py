"""Message lint for relation errors: plain Dutch, no codes, always an actionable hint."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "app" / "domain" / "relations"
FILES = [ROOT / "validation.py", ROOT / "service.py"]
DEV_ERRORS = {"ValueError", "TypeError", "KeyError", "RuntimeError", "IntegrityError"}
FORBIDDEN_WORDS = re.compile(r"exception|traceback|none|invalid|error", re.IGNORECASE)
CODE_TOKEN = re.compile(r"[A-Z]{2,}_[A-Z_]+")
# Every message must tell the user what to do.
HINT = re.compile(r"controleer|kies|vul|open|gebruik|kort|probeer|ververs|geef|zoek", re.IGNORECASE)


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{x}" for v in node.values)
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


def test_messages_are_found():
    assert sum(len(_messages(p)) for p in FILES) >= 10


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_messages_are_plain_dutch(path):
    for lineno, msg in _messages(path):
        where = f"{path.name}:{lineno}: {msg!r}"
        assert not CODE_TOKEN.search(msg), where
        assert not FORBIDDEN_WORDS.search(msg), where
        assert msg.endswith((".", "?")), where
        assert HINT.search(msg), where
