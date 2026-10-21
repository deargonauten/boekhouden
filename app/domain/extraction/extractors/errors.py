"""Builders for the typed extraction errors (AC 6) with their plain-Dutch texts.

Passing the message explicitly keeps the extractors independent of default
messages on the error classes; the texts are identical to the spec.
"""

from __future__ import annotations

from app.domain.errors import (
    ExtractionFailedError,
    ExtractionRateLimitedError,
    ExtractionTimeoutError,
    ExtractorUnavailableError,
)

UNAVAILABLE_MESSAGE = (
    "Het uitlezen kan nog niet: je bent niet ingelogd bij Claude. "
    "Open Terminal en typ: claude auth login. "
    "Of zet ANTHROPIC_API_KEY in het bestand .env."
)
NO_KEY_MESSAGE = (
    "Het uitlezen kan nog niet: er is geen API-sleutel ingesteld. "
    "Zet ANTHROPIC_API_KEY in het bestand .env. "
    "Of log in bij Claude: open Terminal en typ: claude auth login."
)
RATE_LIMITED_MESSAGE = (
    "Je Claude-limiet is bereikt. Probeer het over een uur nog eens, "
    "of zet ANTHROPIC_API_KEY in .env om per factuur te betalen."
)
FAILED_MESSAGE = "Het uitlezen is niet gelukt. Probeer het opnieuw of vul de gegevens zelf in."


def unavailable(message: str = UNAVAILABLE_MESSAGE) -> ExtractorUnavailableError:
    return ExtractorUnavailableError(message)


def rate_limited() -> ExtractionRateLimitedError:
    return ExtractionRateLimitedError(RATE_LIMITED_MESSAGE)


def timed_out(seconds: int) -> ExtractionTimeoutError:
    return ExtractionTimeoutError(
        f"Het uitlezen duurde te lang (meer dan {seconds} seconden). "
        "Probeer het opnieuw; lukt het niet, vul de factuur dan zelf in."
    )


def failed() -> ExtractionFailedError:
    return ExtractionFailedError(FAILED_MESSAGE)
