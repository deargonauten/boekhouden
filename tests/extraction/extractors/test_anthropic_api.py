import base64
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.domain.errors import (
    ExtractionFailedError,
    ExtractionRateLimitedError,
    ExtractionTimeoutError,
    ExtractorUnavailableError,
)
from app.domain.extraction.extractors.anthropic_api import TOOL_NAME, AnthropicApiExtractor
from app.domain.extraction.types import AccountHint, ExtractionRequest

PAYLOAD = {
    "kind": "invoice",
    "supplier": {"name": "Bakkerij Jansen"},
    "invoice_number": "2026-001",
    "total_incl_cents": 1090,
    "lines": [],
}


def make_request(content_type="application/pdf"):
    return ExtractionRequest(
        content=b"%PDF-1.4 data",
        content_type=content_type,
        filename="x.pdf",
        accounts=(AccountHint("4215", "Kantoorkosten"),),
        vat_codes=("NL_21",),
    )


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def client_with(response=None, error=None):
    messages = FakeMessages(response, error)
    return SimpleNamespace(messages=messages), messages


def tool_response(payload=PAYLOAD, name=TOOL_NAME):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="ok"),
            SimpleNamespace(type="tool_use", name=name, input=payload),
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def extractor(client):
    return AnthropicApiExtractor(
        api_key="sk-x", model="claude-sonnet-5-5", timeout_seconds=30, client=client
    )


def test_success_pdf():
    client, messages = client_with(tool_response())
    inv = extractor(client).extract(make_request())
    assert inv.invoice_number == "2026-001"
    assert json.loads(inv.raw) == PAYLOAD
    kw = messages.kwargs
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert kw["tools"][0]["input_schema"]["type"] == "object"
    content = kw["messages"][0]["content"]
    block = content[0]
    assert block["type"] == "document"
    assert block["source"] == {
        "type": "base64",
        "media_type": "application/pdf",
        "data": base64.standard_b64encode(b"%PDF-1.4 data").decode(),
    }
    assert content[-1]["type"] == "text" and "ISSUED" in content[-1]["text"]


def test_image_block():
    client, messages = client_with(tool_response())
    extractor(client).extract(make_request("image/jpeg"))
    block = messages.kwargs["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"


def test_unsupported_type():
    client, _ = client_with(tool_response())
    with pytest.raises(ExtractionFailedError):
        extractor(client).extract(make_request("application/zip"))


def test_no_tool_use_is_failed():
    client, _ = client_with(SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")]))
    with pytest.raises(ExtractionFailedError):
        extractor(client).extract(make_request())


def test_float_cents_not_rounded():
    client, _ = client_with(tool_response({**PAYLOAD, "total_incl_cents": 10.9}))
    inv = extractor(client).extract(make_request())
    assert inv.total_incl_cents is None


_req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status):
    return cls("x", response=httpx.Response(status, request=_req), body=None)


@pytest.mark.parametrize(
    "error,expected",
    [
        (_status_error(anthropic.RateLimitError, 429), ExtractionRateLimitedError),
        (_status_error(anthropic.AuthenticationError, 401), ExtractorUnavailableError),
        (_status_error(anthropic.PermissionDeniedError, 403), ExtractorUnavailableError),
        (anthropic.APITimeoutError(request=_req), ExtractionTimeoutError),
        (anthropic.APIConnectionError(request=_req), ExtractionFailedError),
        (_status_error(anthropic.InternalServerError, 500), ExtractionFailedError),
        (_status_error(anthropic.BadRequestError, 400), ExtractionFailedError),
    ],
)
def test_error_mapping(error, expected):
    client, _ = client_with(error=error)
    with pytest.raises(expected) as exc:
        extractor(client).extract(make_request())
    assert "Traceback" not in exc.value.message


def test_timeout_message_mentions_seconds():
    client, _ = client_with(error=anthropic.APITimeoutError(request=_req))
    with pytest.raises(ExtractionTimeoutError) as exc:
        extractor(client).extract(make_request())
    assert "30 seconden" in exc.value.message


def test_no_key_no_client_is_unavailable():
    with pytest.raises(ExtractorUnavailableError):
        AnthropicApiExtractor(api_key=None, model="m").extract(make_request())


def test_name_and_model():
    e = extractor(client_with()[0])
    assert (e.name, e.model) == ("anthropic_api", "claude-sonnet-5-5")
