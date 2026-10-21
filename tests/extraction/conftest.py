"""Fixtures for extraction tests (migrated sqlite database, tmp storage, documents)."""

import pytest

from app.domain.documents import add_document
from app.domain.documents.storage import DocumentStorage
from tests.ledger.conftest import (  # noqa: F401
    acc,
    engine,
    jrn,
    make_entry,
    session,
    year2025,
)


def pdf_bytes(n: int = 0) -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%" + str(n).encode() + b"\ntrailer\n%%EOF\n"


@pytest.fixture
def storage(test_settings):
    return DocumentStorage(test_settings.documents_dir)


@pytest.fixture
def make_doc(session, storage):
    """Add + commit a new PDF document; each call gives different bytes."""
    counter = iter(range(1, 1000))

    def _make(name: str = "factuur.pdf"):
        doc = add_document(session, storage, pdf_bytes(next(counter)), name).document
        session.commit()
        return doc

    return _make
