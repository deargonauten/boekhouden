"""Extractor that shells out to the user's own `claude` CLI (headless mode).

Why: the CLI authenticates with the user's own login (`claude auth login`, done
once) and counts against their Claude plan. Our code never touches OAuth
tokens or the CLI's credentials.

Spike (Claude Code 2.1.306, logged in with authMethod claude.ai, 2026-10-21)
-------------------------------------------------------------------------
Confirmed working, ~11 s wall time with `--model haiku` on a one-page PDF:

    claude -p "<prompt>" --output-format json --json-schema '<schema>' \\
        --tools Read --allowedTools Read --add-dir <tempdir> \\
        --permission-mode dontAsk --no-session-persistence --model <alias>

run with `cwd=<tempdir>` and `ANTHROPIC_API_KEY` removed from the environment.

- The prompt is the first argument after `-p`; the options after it are
  variadic-safe in this order (verified). Keep the prompt right after `-p`.
- The CLI's Read tool reads the PDF (text and layout) from the temp dir. With
  `--tools Read` no Bash/Write/Web tool exists, so document content cannot make
  the CLI run anything.
- `--permission-mode dontAsk` answers permission prompts with "no" instead of
  waiting for a human; Read inside the `--add-dir` directory is pre-approved by
  `--allowedTools Read`, so no prompt is needed. (Without a non-interactive mode
  a headless run would hang on any prompt.)
- stdout is ONE JSON envelope: `result` (string), `structured_output` (parsed
  object, present because of `--json-schema`), `is_error`, `api_error_status`,
  `total_cost_usd`, `usage`, `num_turns`. A PDF read takes 3 turns.
- `--bare` must NOT be used: it disables OAuth/keychain and demands an API key.
- Deviation from the spec text: none in the flag set; `--permission-mode` value
  is `dontAsk`.
- CLI flags drift between versions: the CLI version is logged on first use and
  the opt-in `pytest -m live` test is the early-warning check.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.domain.extraction.extractors import errors
from app.domain.extraction.extractors.prompt import build_prompt
from app.domain.extraction.extractors.schema import JSON_SCHEMA, parse_extraction
from app.domain.extraction.types import ExtractedInvoice, ExtractionRequest

logger = logging.getLogger(__name__)

_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_RATE_LIMIT = re.compile(r"usage limit|rate.?limit|limit reached|hit your .*limit|\b429\b", re.I)
_NOT_LOGGED_IN = re.compile(r"not logged in|/login|invalid api key|authentication|\b401\b", re.I)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)

_version_logged = False


class ClaudeCliExtractor:
    name = "claude_cli"

    def __init__(
        self, model: str | None = "sonnet", timeout_seconds: int = 180, cli_path: str | None = None
    ):
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.cli_path = cli_path

    # -- public -------------------------------------------------------------
    def extract(self, request: ExtractionRequest) -> ExtractedInvoice:
        extension = _EXTENSIONS.get(request.content_type)
        if extension is None:
            raise errors.failed()
        binary = self.cli_path or shutil.which("claude")
        if not binary:
            raise errors.unavailable()
        self._log_version_once(binary)

        file_name = f"document{extension}"  # generated, never the original name
        workdir = Path(tempfile.mkdtemp(prefix="bh-extract-"))  # random, mode 0700
        started = time.monotonic()
        try:
            (workdir / file_name).write_bytes(request.content)
            args = [
                binary,
                "-p",
                build_prompt(request, file_ref=file_name),
                "--output-format", "json",
                "--json-schema", json.dumps(JSON_SCHEMA),
                "--tools", "Read",
                "--allowedTools", "Read",
                "--add-dir", str(workdir),
                "--permission-mode", "dontAsk",
                "--no-session-persistence",
                "--model", self.model or "sonnet",
            ]  # fmt: skip
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
            }
            try:
                proc = subprocess.run(
                    args,
                    cwd=str(workdir),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                logger.warning("claude_cli timeout after %ss", self.timeout_seconds)
                raise errors.timed_out(self.timeout_seconds) from None
            except OSError as exc:
                logger.warning("claude_cli could not start: %s", type(exc).__name__)
                raise errors.unavailable() from None
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        invoice = self._interpret(proc)
        logger.info(
            "claude_cli ok in %.1fs",
            time.monotonic() - started,
        )
        return invoice

    # -- internals ----------------------------------------------------------
    def _interpret(self, proc: subprocess.CompletedProcess) -> ExtractedInvoice:
        envelope = self._load_json(proc.stdout)
        if not isinstance(envelope, dict):
            logger.warning(
                "claude_cli no JSON envelope (rc=%s, stderr=%.200s)", proc.returncode, proc.stderr
            )
            raise errors.failed()

        logger.info(
            "claude_cli cost_usd=%s usage=%s",
            envelope.get("total_cost_usd"),
            envelope.get("usage"),
        )
        if envelope.get("is_error") or proc.returncode != 0:
            raise self._map_error(envelope, proc.returncode)

        structured = envelope.get("structured_output")
        if isinstance(structured, dict):
            payload: Any = structured
            raw = json.dumps(structured, ensure_ascii=False)
        else:
            text = envelope.get("result")
            payload = self._load_json(text) if isinstance(text, str) else None
            raw = text if isinstance(text, str) else None
            if not isinstance(payload, dict):
                logger.warning("claude_cli result is not a JSON object")
                raise errors.failed()
        invoice = parse_extraction(payload)
        return _with_raw(invoice, raw)

    @staticmethod
    def _load_json(text: Any) -> Any:
        if not isinstance(text, str):
            return None
        text = text.strip()
        match = _FENCE.match(text)
        if match:
            text = match.group(1)
        try:
            return json.loads(text)
        except ValueError:
            return None

    @staticmethod
    def _map_error(envelope: dict, returncode: int) -> Exception:
        message = envelope.get("result") if isinstance(envelope.get("result"), str) else ""
        status = envelope.get("api_error_status")
        logger.warning(
            "claude_cli error rc=%s status=%s subtype=%s", returncode, status, envelope.get("subtype")
        )
        if status == 429 or _RATE_LIMIT.search(message):
            return errors.rate_limited()
        if status == 401 or _NOT_LOGGED_IN.search(message):
            return errors.unavailable()
        return errors.failed()

    @staticmethod
    def _log_version_once(binary: str) -> None:
        global _version_logged
        if _version_logged:
            return
        _version_logged = True
        try:
            out = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10
            ).stdout
            logger.info("claude CLI version: %s", (out or "").strip())
        except Exception:  # noqa: BLE001 - purely informational
            logger.info("claude CLI version unknown")


def _with_raw(invoice: ExtractedInvoice, raw: str | None) -> ExtractedInvoice:
    return replace(invoice, raw=raw) if raw is not None else invoice
