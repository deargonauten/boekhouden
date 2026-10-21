"""In-memory extractor for tests: no network, no subprocess."""

from __future__ import annotations

from app.domain.extraction.types import ExtractedInvoice, ExtractionRequest


class FakeExtractor:
    """Returns a preset `ExtractedInvoice` or raises a preset error.

    Every request is recorded in `requests`.
    """

    def __init__(
        self,
        result: ExtractedInvoice | None = None,
        *,
        error: Exception | None = None,
        name: str = "fake",
        model: str | None = None,
    ):
        self.result = result if result is not None else ExtractedInvoice()
        self.error = error
        self.name = name
        self.model = model
        self.requests: list[ExtractionRequest] = []

    def extract(self, request: ExtractionRequest) -> ExtractedInvoice:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result
