"""Message lint: user-facing domain messages are plain Dutch sentences."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "app" / "domain"
FILES = [
    ROOT / "ledger" / "service.py",
    ROOT / "ledger" / "entries.py",
    ROOT / "ledger" / "periods.py",
    ROOT / "money.py",
]
# Developer-facing exceptions keep their technical messages.
DEV_ERRORS = {"TypeError", "ValueError", "KeyError", "RuntimeError", "AssertionError"}
FORBIDDEN_WORDS = re.compile(r"exception|traceback|none|invalid", re.IGNORECASE)
CODE_TOKEN = re.compile(r"[A-Z]{2,}_[A-Z_]+")


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{x}" for v in node.values)
    return None


def _messages(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == "_error" and len(node.args) >= 2:
            msg = _literal(node.args[1])
        elif name.endswith("Error") and name not in DEV_ERRORS and name != "LedgerError" and node.args:
            msg = _literal(node.args[0])
        else:
            continue
        if msg is not None:
            found.append((node.lineno, msg))
    return found


def test_messages_are_found():
    assert sum(len(_messages(p)) for p in FILES) > 20


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_messages_are_plain_dutch(path):
    for lineno, msg in _messages(path):
        where = f"{path.name}:{lineno}: {msg!r}"
        assert not CODE_TOKEN.search(msg), where
        assert not FORBIDDEN_WORDS.search(msg), where
        assert msg.endswith((".", "?")), where
