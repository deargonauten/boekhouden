"""Fallback extractor using the official `anthropic` SDK (API key, pay per token).

`anthropic` is imported lazily so the app starts without it configured.
The document is sent as a base64 `document` (PDF) or `image` block, and a single
forced tool call returns the structured result.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import replace
from typing import Any

from app.domain.extraction.extractors import errors
from app.domain.extraction.extractors.prompt import build_prompt
from app.domain.extraction.extractors.schema import JSON_SCHEMA, parse_extraction
from app.domain.extraction.types import ExtractedInvoice, ExtractionRequest

logger = logging.getLogger(__name__)

TOOL_NAME = "record_invoice"
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
_MAX_TOKENS = 4096


class AnthropicApiExtractor:
    name = "anthropic_api"

    def __init__(
        self,
        api_key: str | None,
        model: str | None = "claude-sonnet-5-5",
        timeout_seconds: int = 180,
        client: Any = None,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.api_key:
                raise errors.unavailable(errors.NO_KEY_MESSAGE)
            import anthropic  # lazy: the app must start without it configured

            self._client = anthropic.Anthropic(
                api_key=self.api_key, timeout=float(self.timeout_seconds), max_retries=1
            )
        return self._client

    @staticmethod
    def _document_block(request: ExtractionRequest) -> dict:
        data = base64.standard_b64encode(request.content).decode("ascii")
        if request.content_type == "application/pdf":
            kind = "document"
        elif request.content_type in _IMAGE_TYPES:
            kind = "image"
        else:
            raise errors.failed()
        return {
            "type": kind,
            "source": {"type": "base64", "media_type": request.content_type, "data": data},
        }

    def extract(self, request: ExtractionRequest) -> ExtractedInvoice:
        content = [self._document_block(request), {"type": "text", "text": build_prompt(request)}]
        client = self._get_client()
        import anthropic

        started = time.monotonic()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=_MAX_TOKENS,
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": "Record the data extracted from the document.",
                        "input_schema": JSON_SCHEMA,
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.RateLimitError:
            raise errors.rate_limited() from None
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise errors.unavailable(errors.NO_KEY_MESSAGE) from None
        except anthropic.APITimeoutError:
            raise errors.timed_out(self.timeout_seconds) from None
        except anthropic.APIError as exc:
            logger.warning("anthropic_api error: %s", type(exc).__name__)
            raise errors.failed() from None

        usage = getattr(response, "usage", None)
        logger.info(
            "anthropic_api ok in %.1fs usage=%s",
            time.monotonic() - started,
            getattr(usage, "model_dump", lambda: usage)() if usage else None,
        )
        for block in getattr(response, "content", None) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                payload = block.input
                invoice = parse_extraction(payload)
                return replace(invoice, raw=json.dumps(payload, ensure_ascii=False))
        logger.warning("anthropic_api response had no tool call")
        raise errors.failed()
