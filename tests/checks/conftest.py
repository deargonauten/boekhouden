"""Fixtures for the controle-voor-aangifte tests: migrated temp database plus data builders."""

from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import create_db_engine
from app.domain.vat.periods import VatPeriod
from app.models import (
    Account,
    BankAccount,
    BankImportBatch,
    BankTransaction,
    Contact,
    Document,
    Journal,
    JournalEntry,
    JournalLine,
    Period,
    SalesInvoice,
)
from tests.conftest import migrate_to_head
from tests.vat.vat_helpers import Book

Q3 = VatPeriod(2026, "quarter", 3)
INSIDE = date(2026, 8, 15)
NOW = datetime(2026, 10, 1)


@pytest.fixture
def engine(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    migrate_to_head(test_settings)
    engine = create_db_engine(test_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def book(session):
    return Book(session)


@pytest.fixture
def manual(book):
    """Post a manual/bank direct booking (no source_type) in the bank journal."""

    def _post(lines, **kw):
        kw.setdefault("journal", "BANK")
        return book.post(lines, **kw)

    return _post


@pytest.fixture
def make_txn(session):
    state: dict = {}

    def _make(amount=-12100, day=INSIDE, status="nieuw", desc="Betaling", name="Bol B.V."):
        if "batch" not in state:
            bank_acc = session.scalar(select(Account.id).where(Account.code == "1210"))
            journal = session.scalar(select(Journal.id).where(Journal.code == "BANK"))
            ba = BankAccount(name="ING", iban="NL91ABNA0417164300", account_id=bank_acc, journal_id=journal)
            session.add(ba)
            session.flush()
            batch = BankImportBatch(
                bank_account_id=ba.id, status="afgerond", original_filename="x.csv", sha256="0" * 64,
                ext="csv", size=1, detected_format="csv", created_at=NOW,
            )
            session.add(batch)
            session.flush()
            state.update(batch=batch.id, acc=ba.id, n=0)
        state["n"] += 1
        t = BankTransaction(
            bank_account_id=state["acc"], import_batch_id=state["batch"], booking_date=day,
            amount_cents=amount, currency="EUR", counterparty_name=name, description=desc,
            dedupe_key=f"k{state['n']}", occurrence=1, raw="{}", status=status, created_at=NOW,
        )
        session.add(t)
        session.flush()
        return t

    return _make


@pytest.fixture
def make_doc(session):
    n = iter(range(1, 1000))

    def _make(status="nieuw", received=INSIDE, entry_id=None, name="factuur.pdf"):
        i = next(n)
        d = Document(
            sha256=f"{i:064d}", original_filename=name, content_type="application/pdf", size_bytes=1,
            status=status, source="upload", journal_entry_id=entry_id,
            received_at=datetime(received.year, received.month, received.day, 10),
            created_at=NOW, updated_at=NOW,
        )
        session.add(d)
        session.flush()
        return d

    return _make


@pytest.fixture
def make_invoice(session):
    contact: list[Contact] = []
    numbers = iter(range(1, 1000))

    def _make(status="concept", day=INSIDE, total=12100, name="Jansen Installatie", entry_id=None):
        if not contact:
            c = Contact(name=name, name_key=name.lower(), is_customer=True, country="NL",
                        is_active=True, created_at=NOW, updated_at=NOW)
            session.add(c)
            session.flush()
            contact.append(c)
        extra = {}
        if status == "definitief":
            n = next(numbers)
            extra = dict(
                number=f"2026-{n:04d}", number_year=2026, number_seq=n, pdf_sha256="a" * 64,
                seller_name="Ik", buyer_name=name, journal_entry_id=entry_id,
            )
        inv = SalesInvoice(
            **extra,
            status=status, contact_id=contact[0].id, invoice_date=day, payment_term_days=30,
            due_date=day, total_incl_cents=total, created_at=NOW, updated_at=NOW,
        )
        session.add(inv)
        session.flush()
        return inv

    return _make


@pytest.fixture
def raw_entry(session, book):
    """Insert an entry with arbitrary lines directly, bypassing the ledger's balance check.
    Lines are (account_code, debit, credit)."""
    counter = iter(range(1, 1000))

    def _make(lines, day=INSIDE, desc="Kapot", journal="MEM", source_type=None):
        jid = session.scalar(select(Journal.id).where(Journal.code == journal))
        pid = session.scalar(select(Period.id).where(Period.start_date <= day, Period.end_date >= day))
        e = JournalEntry(
            journal_id=jid, period_id=pid, entry_number=f"RAW-{next(counter):04d}", booking_date=day,
            description=desc, kind="normal", source_type=source_type,
        )
        session.add(e)
        session.flush()
        for no, (code, debit, credit) in enumerate(lines, 1):
            session.add(JournalLine(entry_id=e.id, line_no=no, account_id=book.acc(code),
                                    debit_cents=debit, credit_cents=credit))
        session.flush()
        return e

    return _make
