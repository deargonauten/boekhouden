import json
import subprocess

import pytest

from app.config import Settings
from app.domain.errors import ExtractorUnavailableError
from app.domain.extraction.extractors import factory
from app.domain.extraction.extractors.anthropic_api import AnthropicApiExtractor
from app.domain.extraction.extractors.claude_cli import ClaudeCliExtractor


@pytest.fixture(autouse=True)
def reset_cache():
    factory.reset_cli_status_cache()
    yield
    factory.reset_cli_status_cache()


def settings(**kw):
    return Settings(_env_file=None, **kw)


class Auth:
    def __init__(self, logged_in=True, raises=None, stdout=None, returncode=0):
        self.logged_in, self.raises, self.returncode = logged_in, raises, returncode
        self.stdout = stdout if stdout is not None else json.dumps({"loggedIn": logged_in})
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr="")


def have_binary(monkeypatch, found=True):
    monkeypatch.setattr(
        factory.shutil, "which", lambda name: "/usr/local/bin/claude" if found else None
    )


def test_cli_status_ready(monkeypatch):
    have_binary(monkeypatch)
    auth = Auth(True)
    monkeypatch.setattr(subprocess, "run", auth)
    assert factory.cli_status(settings()) == "ready"
    args, kwargs = auth.calls[0]
    assert args == ["/usr/local/bin/claude", "auth", "status"]
    assert not kwargs.get("shell")


def test_cli_status_not_logged_in(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(False))
    assert factory.cli_status(settings()) == "not_logged_in"


def test_cli_status_missing(monkeypatch):
    have_binary(monkeypatch, found=False)
    assert factory.cli_status(settings()) == "missing"


def test_cli_status_uses_configured_path(monkeypatch):
    have_binary(monkeypatch, found=False)
    auth = Auth(True)
    monkeypatch.setattr(subprocess, "run", auth)
    assert factory.cli_status(settings(claude_cli_path="/opt/claude")) == "ready"
    assert auth.calls[0][0][0] == "/opt/claude"


@pytest.mark.parametrize(
    "auth",
    [
        Auth(raises=subprocess.TimeoutExpired("claude", 15)),
        Auth(stdout="garbage"),
        Auth(stdout="[]"),
        Auth(returncode=1, stdout=""),
    ],
)
def test_cli_status_errors_mean_not_logged_in(monkeypatch, auth):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", auth)
    assert factory.cli_status(settings()) == "not_logged_in"


def test_cli_status_oserror_is_missing(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(raises=FileNotFoundError()))
    assert factory.cli_status(settings()) == "missing"


def test_cli_status_cached_for_60_seconds(monkeypatch):
    have_binary(monkeypatch)
    auth = Auth(True)
    monkeypatch.setattr(subprocess, "run", auth)
    now = [1000.0]
    monkeypatch.setattr(factory.time, "monotonic", lambda: now[0])
    s = settings()
    factory.cli_status(s)
    now[0] += 59
    factory.cli_status(s)
    assert len(auth.calls) == 1
    now[0] += 2
    factory.cli_status(s)
    assert len(auth.calls) == 2


def test_auto_prefers_cli(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(True))
    ext = factory.get_extractor(settings(anthropic_api_key="sk-x", extraction_model="haiku",
                                         extraction_timeout_seconds=99))
    assert isinstance(ext, ClaudeCliExtractor)
    assert ext.model == "haiku" and ext.timeout_seconds == 99


def test_auto_falls_back_to_api_key(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(False))
    ext = factory.get_extractor(settings(anthropic_api_key="sk-x"))
    assert isinstance(ext, AnthropicApiExtractor)
    assert ext.model == "claude-sonnet-5-5" and ext.api_key == "sk-x"


def test_auto_api_key_when_cli_missing(monkeypatch):
    have_binary(monkeypatch, found=False)
    assert isinstance(factory.get_extractor(settings(anthropic_api_key="sk-x")), AnthropicApiExtractor)


def test_auto_nothing_available(monkeypatch):
    have_binary(monkeypatch, found=False)
    with pytest.raises(ExtractorUnavailableError) as exc:
        factory.get_extractor(settings())
    assert "claude auth login" in exc.value.message and ".env" in exc.value.message


def test_forced_cli_not_ready(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(False))
    with pytest.raises(ExtractorUnavailableError):
        factory.get_extractor(settings(extraction_backend="claude_cli", anthropic_api_key="sk-x"))


def test_forced_cli_ready(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(True))
    ext = factory.get_extractor(settings(extraction_backend="claude_cli"))
    assert isinstance(ext, ClaudeCliExtractor)


def test_forced_api_without_key(monkeypatch):
    have_binary(monkeypatch)
    monkeypatch.setattr(subprocess, "run", Auth(True))
    with pytest.raises(ExtractorUnavailableError) as exc:
        factory.get_extractor(settings(extraction_backend="anthropic_api"))
    assert "ANTHROPIC_API_KEY" in exc.value.message


def test_forced_api_ignores_cli(monkeypatch):
    auth = Auth(True)
    monkeypatch.setattr(subprocess, "run", auth)
    ext = factory.get_extractor(settings(extraction_backend="anthropic_api", anthropic_api_key="sk-x"))
    assert isinstance(ext, AnthropicApiExtractor)
    assert auth.calls == []
