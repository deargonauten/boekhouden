"""Nakijken: koppel een mogelijke betaling aan de factuur (uitklapbaar blok, boeken in één stap)."""

from datetime import date, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.bank.accounts import create_bank_account
from app.domain.extraction.extractors.fake import FakeExtractor
from app.models import Account, BankImportBatch, BankTransaction
from tests.test_extraction_web import (  # noqa: F401  (fixtures and helpers)
    INVOICE, _clean_overrides, cli_ready, read_out, review_data, sql,
)

IBAN = "NL91ABNA0417164300"
PAID = date(2026, 3, 5)


@pytest.fixture
def bank(client):
    assert client.post("/instellingen/boekjaren", data={"year": 2026}, follow_redirects=False).status_code == 303
    engine = client.app.state.engine
    with Session(engine) as s:
        account = create_bank_account(s, "Zakelijk", IBAN, s.scalar(select(Account.id).where(Account.code == "1210")), "ing")
        batch = BankImportBatch(
            bank_account_id=account.id, status="afgerond", original_filename="x.csv", sha256="0" * 64,
            ext="csv", size=1, detected_format="csv", created_at=datetime.now(),
        )
        s.add(batch)
        s.commit()
        ids = (account.id, batch.id)
    counter = iter(range(1, 100))

    def add(amount=-12100, desc="Betaling", name="Jansen"):
        with Session(engine) as s:
            t = BankTransaction(
                bank_account_id=ids[0], import_batch_id=ids[1], booking_date=PAID, amount_cents=amount,
                currency="EUR", counterparty_name=name, description=desc, dedupe_key=f"k{next(counter)}",
                occurrence=1, raw="{}", status="nieuw", created_at=datetime.now(),
            )
            s.add(t)
            s.commit()
            return t.id

    return add


def test_only_possible_payments_are_listed(client, bank):
    match = bank(-12100, "Factuur 2026-001")
    bank(-999, "Iets anders")  # wrong amount, no sign
    bank(12100, "Terugbetaling")  # money in
    doc_id = read_out(client)
    html = client.get(f"/inbox/{doc_id}/nakijken").text
    assert "Al betaald? Koppel een betaling" in html
    assert f'name="bank_transaction_id" value="{match}"' in html
    assert html.count('name="bank_transaction_id"') == 2  # 'geen' + the one candidate
    assert "1 mogelijke betaling" in html


def test_no_candidates_says_so(client, bank):
    bank(-999)
    html = client.get(f"/inbox/{read_out(client)}/nakijken").text
    assert "Er is geen betaling gevonden" in html
    assert 'name="bank_transaction_id"' not in html


def test_booking_with_payment_links_it(client, bank):
    txn = bank()
    doc_id = read_out(client)
    r = client.post(
        f"/inbox/{doc_id}/nakijken",
        data=review_data(client, actie="boeken", bank_transaction_id=str(txn)),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert sql(client, "SELECT status FROM bank_transaction WHERE id = :i", i=txn)[0][0] == "geboekt"
    assert sql(client, "SELECT paid_cents, total_incl_cents FROM purchase_invoice")[0] == (12100, 12100)
    assert sql(client, "SELECT count(*) FROM bank_match WHERE bank_transaction_id = :i", i=txn)[0][0] == 1


def test_booking_without_choice_leaves_the_payment_alone(client, bank):
    txn = bank()
    doc_id = read_out(client)
    r = client.post(
        f"/inbox/{doc_id}/nakijken",
        data=review_data(client, actie="boeken", bank_transaction_id=""),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert sql(client, "SELECT status FROM bank_transaction WHERE id = :i", i=txn)[0][0] == "nieuw"
    assert sql(client, "SELECT paid_cents FROM purchase_invoice")[0][0] == 0


def test_unrelated_payment_is_refused_and_nothing_is_booked(client, bank):
    other = bank(-999, "Iets anders")
    doc_id = read_out(client)
    r = client.post(
        f"/inbox/{doc_id}/nakijken",
        data=review_data(client, actie="boeken", bank_transaction_id=str(other)),
    )
    assert r.status_code == 422
    assert "past niet bij de factuur" in r.text
    assert sql(client, "SELECT count(*) FROM purchase_invoice")[0][0] == 0
    assert sql(client, "SELECT status FROM bank_transaction WHERE id = :i", i=other)[0][0] == "nieuw"
