"""Fixtures for beginbalans service tests: a migrated database, boekjaar 2025, relaties."""

import pytest

from app.domain.relations import ContactInput, create_contact
from tests.ledger.conftest import (  # noqa: F401
    acc,
    engine,
    jrn,
    make_entry,
    session,
    year2025,
)


@pytest.fixture
def make_contact(session):
    def _make(name: str, *, customer: bool = False, supplier: bool = False):
        contact = create_contact(
            session, ContactInput(name=name, is_customer=customer, is_supplier=supplier or not customer)
        )
        session.commit()
        return contact

    return _make
