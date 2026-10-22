"""Fixtures for purchase booking tests: a migrated database with a reviewed extraction."""

from datetime import date, datetime

import pytest

from app.domain.documents import mark_recognized
from app.domain.relations import ContactInput, create_contact
from app.models import InvoiceExtraction, InvoiceExtractionLine
from tests.extraction.conftest import make_doc, pdf_bytes, storage  # noqa: F401
from tests.ledger.conftest import (  # noqa: F401
    acc,
    engine,
    jrn,
    make_entry,
    session,
    year2025,
)

DAY = date(2025, 3, 10)


@pytest.fixture
def make_supplier(session):
    def _make(name: str = "Bol B.V."):
        contact = create_contact(session, ContactInput(name=name, is_supplier=True))
        session.commit()
        return contact

    return _make


@pytest.fixture
def make_extraction(session, make_doc, make_supplier, acc):
    """A document with an extraction; defaults: reviewed, ok, one 100 + 21 line on 4200."""

    def _make(
        *,
        lines=None,
        contact=None,
        reviewed=True,
        status="ok",
        number="F-1",
        day=DAY,
        kind="invoice",
        totals=None,
        currency="EUR",
        due_date=None,
    ):
        doc = make_doc()
        if contact is None:
            contact = make_supplier()
        lines = lines if lines is not None else [("Papier", 10000, 2100, "NL_21", "4200")]
        excl = sum(l[1] or 0 for l in lines)
        vat = sum(l[2] or 0 for l in lines)
        t_excl, t_vat, t_incl = totals or (excl, vat, excl + vat)
        now = datetime(2025, 3, 11, 12, 0)
        ex = InvoiceExtraction(
            document_id=doc.id,
            status=status,
            extractor="test",
            kind=kind,
            supplier_name=contact.name if contact else None,
            contact_id=contact.id if contact else None,
            invoice_number=number,
            invoice_date=day,
            due_date=due_date,
            currency=currency,
            total_excl_cents=t_excl,
            total_vat_cents=t_vat,
            total_incl_cents=t_incl,
            reviewed_at=now if reviewed else None,
            created_at=now,
            updated_at=now,
        )
        session.add(ex)
        session.flush()
        for pos, (desc, amount, vat_amount, code, account_code) in enumerate(lines):
            session.add(
                InvoiceExtractionLine(
                    extraction_id=ex.id,
                    position=pos,
                    description=desc,
                    amount_excl_cents=amount,
                    vat_amount_cents=vat_amount,
                    vat_code=code,
                    account_id=acc(account_code) if account_code else None,
                )
            )
        mark_recognized(session, doc.id)
        session.commit()
        return doc

    return _make
