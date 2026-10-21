"""Fixtures for document tests (migrated sqlite database + tmp storage)."""

import pytest

from app.domain.documents.storage import DocumentStorage
from tests.ledger.conftest import (  # noqa: F401
    acc,
    engine,
    jrn,
    make_entry,
    session,
    year2025,
)

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 " + b"\x00" * 20


@pytest.fixture
def storage(test_settings):
    return DocumentStorage(test_settings.documents_dir)
