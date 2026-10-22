"""Fixtures for sales tests: a migrated database with boekjaar 2026, own company data and a klant."""

from datetime import date

import pytest

from app.domain.company import get_company_profile  # noqa: F401
from app.domain.company.service import save_company_profile
from app.domain.company.validation import CompanyInput
from app.domain.documents.storage import DocumentStorage
from app.domain.ledger import create_fiscal_year
from app.domain.relations import ContactInput, create_contact
from app.domain.sales import ConceptInput, LineInput, create_concept, finalize
from sqlalchemy.orm import Session

from tests.ledger.conftest import acc, engine, jrn  # noqa: F401

DAY = date(2026, 3, 10)


@pytest.fixture
def session(engine):
    """Like the app's sessions (SessionLocal): no autoflush, so missing flushes show up."""
    with Session(engine, expire_on_commit=False, autoflush=False) as s:
        yield s


@pytest.fixture
def storage(tmp_path):
    return DocumentStorage(tmp_path / "docs")


@pytest.fixture
def year2026(session):
    fy = create_fiscal_year(session, 2026)
    session.commit()
    return fy


@pytest.fixture
def company(session):
    save_company_profile(
        session,
        CompanyInput(
            legal_name="Jansen Webdesign", legal_form="eenmanszaak", address_line="Dorpsstraat 1",
            postal_code="1234 AB", city="Utrecht", kvk="12345678", btw_id="NL123456789B01",
            iban="NL91ABNA0417164300", email="info@jansen.nl",
        ),
    )
    session.commit()


@pytest.fixture
def make_customer(session):
    def _make(name="Klant BV", **kw):
        kw.setdefault("address_line", "Hoofdweg 2")
        kw.setdefault("postal_code", "1000 AA")
        kw.setdefault("city", "Amsterdam")
        kw.setdefault("is_customer", True)
        contact = create_contact(session, ContactInput(name=name, **kw))
        session.commit()
        return contact

    return _make


@pytest.fixture
def customer(make_customer):
    return make_customer()


@pytest.fixture
def ready(year2026, company):
    """Boekjaar and company data are in place."""


@pytest.fixture
def make_concept(session, acc, ready):
    def _make(contact, *, day=DAY, lines=None, **kw):
        lines = lines if lines is not None else [LineInput("Website", 1000, 10000, "NL_21", acc("8000"))]
        inv = create_concept(session, ConceptInput(contact_id=contact.id, invoice_date=day, lines=lines, **kw))
        session.commit()
        return inv

    return _make


@pytest.fixture
def make_final(session, make_concept, storage):
    def _make(contact, **kw):
        inv = make_concept(contact, **kw)
        finalize(session, inv.id, storage=storage)
        session.commit()
        return inv

    return _make
