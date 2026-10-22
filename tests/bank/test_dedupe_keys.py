from dataclasses import replace
from datetime import date
from pathlib import Path

from app.domain.bank.dedupe import compute_keys, dedupe_key, normalize_text
from app.domain.bank.parsers import parse_statement
from app.domain.bank.types import ParsedTransaction

FIXTURES = Path(__file__).parent / "parsers" / "fixtures"


def tx(**kw):
    base = dict(
        booking_date=date(2024, 3, 1),
        amount_cents=-1210,
        counterparty_iban="NL02ABNA0123456789",
        description="Factuur 1",
        end_to_end_id="E2E-1",
    )
    base.update(kw)
    return ParsedTransaction(**base)


def test_normalize_text():
    assert normalize_text("  Factuur \t 1\nKOFFIE ") == "factuur 1 koffie"
    assert normalize_text(None) == ""


def test_key_is_stable_and_hex_sha256():
    key = dedupe_key(1, tx())
    assert key == dedupe_key(1, tx()) and len(key) == 64 and int(key, 16) >= 0


def test_key_ignores_whitespace_case_and_iban_format():
    a = dedupe_key(1, tx())
    b = dedupe_key(1, tx(description="  FACTUUR   1 ", counterparty_iban="nl02 abna 0123 4567 89"))
    assert a == b


def test_key_differs_per_field():
    base = dedupe_key(1, tx())
    assert dedupe_key(2, tx()) != base
    assert dedupe_key(1, tx(booking_date=date(2024, 3, 2))) != base
    assert dedupe_key(1, tx(amount_cents=-1211)) != base
    assert dedupe_key(1, tx(counterparty_iban=None)) != base
    assert dedupe_key(1, tx(end_to_end_id="E2E-2")) != base
    assert dedupe_key(1, tx(description="Factuur 2")) != base


def test_reference_falls_back_to_bank_reference_then_empty():
    by_bank_ref = tx(end_to_end_id=None, bank_reference="REF-1")
    assert dedupe_key(1, by_bank_ref) != dedupe_key(1, tx(end_to_end_id=None))
    assert dedupe_key(1, by_bank_ref) == dedupe_key(1, replace(by_bank_ref, bank_reference=" ref-1 "))
    # e2e id wins over the bank reference
    assert dedupe_key(1, tx(bank_reference="X")) == dedupe_key(1, tx(bank_reference="Y"))


def test_identical_lines_get_occurrence_numbers():
    coffee = tx(description="Koffie", end_to_end_id=None, amount_cents=-350)
    other = tx()
    keys = compute_keys(1, [coffee, other, coffee, coffee])
    assert [k[1] for k in keys] == [1, 1, 2, 3]
    assert keys[0][0] == keys[2][0] == keys[3][0] and keys[1][0] != keys[0][0]


def test_compute_keys_accepts_statement_and_is_deterministic():
    st = parse_statement((FIXTURES / "camt053_002.xml").read_bytes())
    again = parse_statement((FIXTURES / "camt053_002.xml").read_bytes())
    keys = compute_keys(7, st)
    assert keys == compute_keys(7, again.transactions)
    assert len({k for k in keys}) == len(keys)
    coffees = [k for k, t in zip(keys, st.transactions) if t.description == "Koffie"]
    assert [c[1] for c in coffees] == [1, 2]


def test_overlapping_file_shares_keys_for_shared_rows():
    st = parse_statement((FIXTURES / "camt053_002.xml").read_bytes())
    overlap = compute_keys(1, st.transactions[2:])  # a later statement starting mid-way
    full = compute_keys(1, st.transactions)
    assert overlap == full[2:]  # the coffees keep occurrence 1 and 2


def test_same_transactions_in_other_format_differ_in_key():
    """CAMT vs MT940 of the same payment differ in description/reference: that is what the fuzzy check is for."""
    camt = parse_statement((FIXTURES / "camt053_002.xml").read_bytes()).transactions[0]
    csv_tx = parse_statement((FIXTURES / "ing.csv").read_bytes()).transactions[0]
    assert (camt.booking_date, camt.amount_cents, camt.counterparty_iban) == (
        csv_tx.booking_date,
        csv_tx.amount_cents,
        csv_tx.counterparty_iban,
    )
    assert dedupe_key(1, camt) != dedupe_key(1, csv_tx)
