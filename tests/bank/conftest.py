"""Fixtures for bank import tests: migrated database, bank storage, sample files."""

from pathlib import Path

import pytest

from app.domain.bank.accounts import create_bank_account
from app.domain.bank.storage import BankFileStorage
from tests.ledger.conftest import acc, engine, jrn, session  # noqa: F401

FIXTURES = Path(__file__).parent / "parsers" / "fixtures"

ING_IBAN = "NL20INGB0001234567"
ABN_IBAN = "NL91ABNA0417164300"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def bank_storage(tmp_path):
    return BankFileStorage(tmp_path / "data" / "bank")


@pytest.fixture
def ing_account(session, acc):
    """Bankrekening on 1210 with the ING IBAN used by the ING fixtures."""
    ba = create_bank_account(session, "Zakelijk ING", ING_IBAN, acc("1210"), "ing")
    session.commit()
    return ba


@pytest.fixture
def abn_account(session, acc):
    ba = create_bank_account(session, "Zakelijk ABN", ABN_IBAN, acc("1220"), "abn_amro")
    session.commit()
    return ba
