"""Fixtures for reconcile service tests: boekjaar 2025, bankrekening, leveranciers, facturen."""

from datetime import date, datetime

import pytest

from app.domain.opening import OpeningInput, OpeningItemInput, book_opening_balance
from app.domain.purchase import book_extraction
from app.models import BankImportBatch, BankTransaction
from tests.bank.conftest import ING_IBAN, ing_account  # noqa: F401
from tests.purchase.conftest import (  # noqa: F401
    acc,
    engine,
    jrn,
    make_entry,
    make_doc,
    make_extraction,
    make_supplier,
    pdf_bytes,
    session,
    storage,
    year2025,
)

SUPPLIER_IBAN = "NL91ABNA0417164300"
DAY = date(2025, 4, 1)


@pytest.fixture
def batch(session, ing_account):
    b = BankImportBatch(
        bank_account_id=ing_account.id, status="afgerond", original_filename="x.csv", sha256="0" * 64,
        ext="csv", size=1, detected_format="csv", created_at=datetime(2025, 4, 2),
    )
    session.add(b)
    session.commit()
    return b


@pytest.fixture
def make_txn(session, ing_account, batch):
    counter = iter(range(1, 1000))

    def _make(amount=-12100, desc="Betaling", name="Bol B.V.", iban=SUPPLIER_IBAN, day=DAY, ref=None):
        n = next(counter)
        t = BankTransaction(
            bank_account_id=ing_account.id, import_batch_id=batch.id, booking_date=day,
            amount_cents=amount, currency="EUR", counterparty_name=name, counterparty_iban=iban,
            description=desc, bank_reference=ref, dedupe_key=f"k{n}", occurrence=1, raw="{}",
            status="nieuw", created_at=datetime(2025, 4, 2),
        )
        session.add(t)
        session.commit()
        return t

    return _make


@pytest.fixture
def invoice(session, year2025, make_supplier, make_extraction):
    """Factuur F-1 van Bol B.V.: 100,00 + 21,00 = 121,00 (IBAN set on the leverancier)."""

    def _make(number="F-1", lines=None, contact=None, kind="invoice", day=date(2025, 3, 10)):
        supplier = contact or make_supplier("Bol B.V.")
        if supplier.iban is None:
            supplier.iban = SUPPLIER_IBAN
            session.commit()
        doc = make_extraction(contact=supplier, number=number, lines=lines, kind=kind, day=day)
        return book_extraction(session, doc.id), supplier

    return _make


@pytest.fixture
def opening_item(session, year2025, make_supplier, acc):
    supplier = make_supplier("Kantoor Plaza")
    book_opening_balance(
        session,
        OpeningInput(
            [(acc("1210"), 50000)],
            [OpeningItemInput("crediteur", supplier.id, "OUD-1", date(2024, 12, 1), None, 4500)],
        ),
    )
    session.commit()
    from app.models import OpeningItem
    from sqlalchemy import select

    return session.scalar(select(OpeningItem)), supplier
