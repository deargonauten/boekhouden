"""Backend selection: `get_extractor(settings)` and `cli_status(settings)`."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Literal

from app.config import Settings
from app.domain.extraction.extractors import errors
from app.domain.extraction.extractors.anthropic_api import AnthropicApiExtractor
from app.domain.extraction.extractors.claude_cli import ClaudeCliExtractor
from app.domain.extraction.types import InvoiceExtractor

logger = logging.getLogger(__name__)

CliStatus = Literal["ready", "not_logged_in", "missing"]

_CACHE_SECONDS = 60
_STATUS_TIMEOUT_SECONDS = 15
_cache: dict[str | None, tuple[float, CliStatus]] = {}


def reset_cli_status_cache() -> None:
    _cache.clear()


def _binary(settings: Settings) -> str | None:
    return settings.claude_cli_path or shutil.which("claude")


def cli_status(settings: Settings) -> CliStatus:
    """Is the `claude` CLI installed and logged in? Cached for 60 seconds."""
    key = settings.claude_cli_path
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    status = _probe(settings)
    _cache[key] = (time.monotonic(), status)
    return status


def _probe(settings: Settings) -> CliStatus:
    binary = _binary(settings)
    if not binary:
        return "missing"
    try:
        proc = subprocess.run(
            [binary, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=_STATUS_TIMEOUT_SECONDS,
        )
    except OSError:
        return "missing"
    except subprocess.TimeoutExpired:
        logger.warning("claude auth status timed out")
        return "not_logged_in"
    if proc.returncode != 0:
        return "not_logged_in"
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return "not_logged_in"
    if isinstance(data, dict) and data.get("loggedIn") is True:
        return "ready"
    return "not_logged_in"


def _api_key(settings: Settings) -> str | None:
    key = settings.anthropic_api_key
    value = key.get_secret_value().strip() if key else ""
    return value or None


def _cli(settings: Settings) -> ClaudeCliExtractor:
    return ClaudeCliExtractor(
        model=settings.extraction_model,
        timeout_seconds=settings.extraction_timeout_seconds,
        cli_path=settings.claude_cli_path,
    )


def _api(settings: Settings, key: str) -> AnthropicApiExtractor:
    return AnthropicApiExtractor(
        api_key=key,
        model=settings.anthropic_model,
        timeout_seconds=settings.extraction_timeout_seconds,
    )


def get_extractor(settings: Settings) -> InvoiceExtractor:
    """Pick the backend from `settings.extraction_backend`.

    auto: Claude CLI when installed and logged in, else the API key, else
    `ExtractorUnavailableError` explaining both options in plain Dutch.
    """
    backend = settings.extraction_backend
    key = _api_key(settings)
    if backend == "anthropic_api":
        if not key:
            raise errors.unavailable(errors.NO_KEY_MESSAGE)
        return _api(settings, key)
    if backend == "claude_cli":
        if cli_status(settings) != "ready":
            raise errors.unavailable()
        return _cli(settings)
    if cli_status(settings) == "ready":
        return _cli(settings)
    if key:
        return _api(settings, key)
    raise errors.unavailable()
