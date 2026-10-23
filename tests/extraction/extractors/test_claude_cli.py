import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from app.domain.errors import (
    ExtractionFailedError,
    ExtractionRateLimitedError,
    ExtractionTimeoutError,
    ExtractorUnavailableError,
)
from app.domain.extraction.extractors import claude_cli
from app.domain.extraction.extractors.claude_cli import ClaudeCliExtractor
from app.domain.extraction.types import AccountHint, ExtractionRequest

PAYLOAD = {
    "kind": "invoice",
    "supplier": {"name": "Bakkerij Jansen"},
    "invoice_number": "2026-001",
    "total_incl_cents": 1090,
    "lines": [{"description": "Brood", "amount_excl_cents": 1000}],
}


def make_request(content_type="application/pdf", filename="mijn factuur; rm -rf ~.pdf"):
    return ExtractionRequest(
        content=b"%PDF-1.4 data",
        content_type=content_type,
        filename=filename,
        accounts=(AccountHint("4215", "Kantoorkosten"),),
        vat_codes=("NL_21",),
    )


def envelope(**over):
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "result": json.dumps(PAYLOAD),
        "structured_output": PAYLOAD,
        "total_cost_usd": 0.01,
        "usage": {"input_tokens": 1},
    }
    base.update(over)
    return base


class Runner:
    """Stand-in for subprocess.run; records the real extraction call."""

    def __init__(self, stdout="", returncode=0, stderr="", raises=None):
        self.stdout, self.returncode, self.stderr, self.raises = stdout, returncode, stderr, raises
        self.calls = []
        self.files_seen = None
        self.dir_mode = None

    def __call__(self, args, **kwargs):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="2.1.306 (Claude Code)\n", stderr="")
        self.calls.append((args, kwargs))
        cwd = Path(kwargs["cwd"])
        self.files_seen = sorted(p.name for p in cwd.iterdir())
        self.dir_mode = stat.S_IMODE(cwd.stat().st_mode)
        self.content_seen = {p.name: p.read_bytes() for p in cwd.iterdir()}
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(
            args, self.returncode, stdout=self.stdout, stderr=self.stderr
        )


@pytest.fixture
def extractor():
    return ClaudeCliExtractor(model="sonnet", timeout_seconds=42, cli_path="/usr/bin/claude")


def run(monkeypatch, extractor, runner, request=None):
    monkeypatch.setattr(subprocess, "run", runner)
    return extractor.extract(request or make_request())


def test_success_parses_structured_output(monkeypatch, extractor):
    runner = Runner(json.dumps(envelope()))
    inv = run(monkeypatch, extractor, runner)
    assert inv.invoice_number == "2026-001"
    assert inv.total_incl_cents == 1090
    assert inv.supplier.name == "Bakkerij Jansen"
    assert json.loads(inv.raw) == PAYLOAD
    assert extractor.name == "claude_cli" and extractor.model == "sonnet"


def test_arguments(monkeypatch, extractor):
    runner = Runner(json.dumps(envelope()))
    run(monkeypatch, extractor, runner)
    args, kwargs = runner.calls[0]
    assert isinstance(args, list)
    assert not kwargs.get("shell")
    assert args[0] == "/usr/bin/claude" and args[1] == "-p"
    assert args[args.index("--output-format") + 1] == "json"
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert schema["type"] == "object"
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--allowedTools") + 1] == "Read"
    assert args[args.index("--add-dir") + 1] == kwargs["cwd"]
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert "--no-session-persistence" in args
    assert args[args.index("--model") + 1] == "sonnet"
    assert "--bare" not in args
    assert kwargs["timeout"] == 42
    assert kwargs["cwd"] != os.getcwd()


def test_prompt_is_generated_not_user_supplied(monkeypatch, extractor):
    runner = Runner(json.dumps(envelope()))
    run(monkeypatch, extractor, runner)
    args, _ = runner.calls[0]
    prompt = args[2]
    assert "document.pdf" in prompt
    assert "rm -rf" not in prompt and "mijn factuur" not in prompt


def test_env_has_no_api_key(monkeypatch, extractor):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    runner = Runner(json.dumps(envelope()))
    run(monkeypatch, extractor, runner)
    env = runner.calls[0][1]["env"]
    assert "ANTHROPIC_API_KEY" not in env
    assert "PATH" in env


def test_temp_dir_private_holds_file_and_is_deleted(monkeypatch, extractor):
    runner = Runner(json.dumps(envelope()))
    run(monkeypatch, extractor, runner)
    cwd = Path(runner.calls[0][1]["cwd"])
    assert runner.files_seen == ["document.pdf"]
    assert runner.content_seen["document.pdf"] == b"%PDF-1.4 data"
    assert runner.dir_mode == 0o700
    assert not cwd.exists()


@pytest.mark.parametrize(
    "content_type,ext",
    [("image/jpeg", ".jpg"), ("image/png", ".png"), ("image/webp", ".webp")],
)
def test_extension_from_content_type(monkeypatch, extractor, content_type, ext):
    runner = Runner(json.dumps(envelope()))
    run(monkeypatch, extractor, runner, make_request(content_type))
    assert runner.files_seen == [f"document{ext}"]


def test_unsupported_content_type(monkeypatch, extractor):
    runner = Runner(json.dumps(envelope()))
    with pytest.raises(ExtractionFailedError):
        run(monkeypatch, extractor, runner, make_request("application/zip"))
    assert runner.calls == []


def test_temp_dir_deleted_on_error(monkeypatch, extractor):
    runner = Runner(raises=subprocess.TimeoutExpired("claude", 42))
    with pytest.raises(ExtractionTimeoutError):
        run(monkeypatch, extractor, runner)
    assert not Path(runner.calls[0][1]["cwd"]).exists()


def test_timeout_message_has_seconds(monkeypatch, extractor):
    runner = Runner(raises=subprocess.TimeoutExpired("claude", 42))
    with pytest.raises(ExtractionTimeoutError) as exc:
        run(monkeypatch, extractor, runner)
    assert "42 seconden" in exc.value.message


def test_fallback_to_result_string(monkeypatch, extractor):
    env = envelope(structured_output=None)
    runner = Runner(json.dumps(env))
    assert run(monkeypatch, extractor, runner).invoice_number == "2026-001"


def test_fallback_result_with_code_fence(monkeypatch, extractor):
    env = envelope(structured_output=None, result="```json\n" + json.dumps(PAYLOAD) + "\n```")
    assert run(monkeypatch, extractor, Runner(json.dumps(env))).invoice_number == "2026-001"


@pytest.mark.parametrize(
    "stdout",
    ["", "not json", "[]", json.dumps(envelope(structured_output=None, result="geen json")),
     json.dumps(envelope(structured_output=None, result=None))],
)
def test_bad_output_is_failed(monkeypatch, extractor, stdout):
    with pytest.raises(ExtractionFailedError) as exc:
        run(monkeypatch, extractor, Runner(stdout))
    assert "Traceback" not in exc.value.message


def test_nonzero_exit_is_failed(monkeypatch, extractor):
    with pytest.raises(ExtractionFailedError) as exc:
        run(monkeypatch, extractor, Runner("", returncode=1, stderr="boom secret detail"))
    assert "boom" not in exc.value.message


def test_is_error_generic_is_failed(monkeypatch, extractor):
    env = envelope(is_error=True, result="Something broke", structured_output=None)
    with pytest.raises(ExtractionFailedError):
        run(monkeypatch, extractor, Runner(json.dumps(env)))


@pytest.mark.parametrize(
    "over",
    [
        {"api_error_status": 429, "result": "API Error: 429"},
        {"result": "You've hit your usage limit. Resets at 5pm"},
        {"result": "Claude AI usage limit reached|1760000000"},
    ],
)
def test_rate_limit(monkeypatch, extractor, over):
    env = envelope(is_error=True, structured_output=None, **over)
    with pytest.raises(ExtractionRateLimitedError):
        run(monkeypatch, extractor, Runner(json.dumps(env), returncode=1))


@pytest.mark.parametrize(
    "over",
    [
        {"api_error_status": 401, "result": "Invalid API key"},
        {"result": "Not logged in · Please run /login"},
    ],
)
def test_not_logged_in(monkeypatch, extractor, over):
    env = envelope(is_error=True, structured_output=None, **over)
    with pytest.raises(ExtractorUnavailableError) as exc:
        run(monkeypatch, extractor, Runner(json.dumps(env), returncode=1))
    assert "claude auth login" in exc.value.message


def test_missing_binary(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: None)
    ext = ClaudeCliExtractor(model="sonnet", timeout_seconds=5)
    with pytest.raises(ExtractorUnavailableError):
        ext.extract(make_request())


def test_oserror_on_start_is_unavailable(monkeypatch, extractor):
    runner = Runner(raises=FileNotFoundError("claude"))
    with pytest.raises(ExtractorUnavailableError):
        run(monkeypatch, extractor, runner)


def test_float_cents_in_structured_output_not_rounded(monkeypatch, extractor):
    payload = {**PAYLOAD, "total_incl_cents": 1090.4}
    env = envelope(structured_output=payload, result=json.dumps(payload))
    inv = run(monkeypatch, extractor, Runner(json.dumps(env)))
    assert inv.total_incl_cents is None
    assert inv.confidence["total_incl_cents"] == "low"


def test_no_invoice_content_logged_at_info(monkeypatch, extractor, caplog):
    import logging

    caplog.set_level(logging.INFO)
    run(monkeypatch, extractor, Runner(json.dumps(envelope())))
    text = caplog.text
    assert "Bakkerij" not in text and "2026-001" not in text
