from datetime import date
from pathlib import Path

import pytest

from app.domain.bank.parsers import format_description, parse_statement
from app.domain.bank.types import (
    EMPTY,
    FILE_TOO_BIG,
    PARSE_ERROR,
    UNKNOWN_FORMAT,
    BankImportError,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def summary(statement):
    return [
        (t.booking_date, t.amount_cents, t.counterparty_name, t.counterparty_iban, t.description)
        for t in statement.transactions
    ]


def assert_balances(statement):
    assert statement.balance_difference_cents == 0


# --- CAMT.053 -------------------------------------------------------------


def test_camt053_002_golden():
    st = parse_statement(load("camt053_002.xml"))
    assert (st.format, st.bank, st.account_iban) == ("camt053", "abn_amro", "NL91ABNA0417164300")
    assert (st.opening_cents, st.closing_cents) == (100000, 215090)
    assert summary(st) == [
        (date(2024, 3, 1), -1210, "Kantoor BV", "NL02ABNA0123456789", "Factuur 2024-001 kantoorartikelen"),
        (date(2024, 3, 2), 100000, "Klant BV", "NL71INGB0009876543", "Betaling factuur 17"),
        (date(2024, 3, 4), -350, None, None, "Koffie"),
        (date(2024, 3, 4), -350, None, None, "Koffie"),
        (date(2024, 3, 4), 10000, "Klant A", None, "Deel A"),
        (date(2024, 3, 4), 5000, "Klant B", None, "Deel B"),
        (date(2024, 3, 4), 2000, None, None, "Terugboeking"),  # reversal of a debit flips the sign
    ]
    assert_balances(st)


def test_camt053_fields():
    st = parse_statement(load("camt053_002.xml"))
    first, second = st.transactions[0], st.transactions[1]
    assert first.end_to_end_id == "E2E-001"
    assert first.bank_reference == "REF-0001"
    assert first.value_date == date(2024, 3, 1)
    assert second.end_to_end_id is None  # NOTPROVIDED
    assert "<Ntry>" in first.raw and "Kantoor BV" in first.raw
    split_a, split_b = st.transactions[4], st.transactions[5]
    assert (split_a.end_to_end_id, split_b.end_to_end_id) == ("BATCH-1", "BATCH-2")
    assert split_a.bank_reference == "REF-0004"


def test_camt053_008_golden():
    st = parse_statement(load("camt053_008.xml"))
    assert (st.bank, st.account_iban) == ("ing", "NL20INGB0001234567")
    assert summary(st) == [
        (date(2024, 3, 1), 1210, "Klant BV", "NL71INGB0009876543", "Terugbetaling"),
    ]
    assert st.opening_cents == -50000 and st.closing_cents == -48790
    assert_balances(st)
    assert st.transactions[0].bank_reference == "ASR-1"


def test_camt053_wrong_extension_and_whitespace_still_detected():
    assert parse_statement(b"\n  " + load("camt053_002.xml")).format == "camt053"


def test_camt053_entity_expansion_is_rejected():
    bomb = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<Document><BkToCstmrStmt><Stmt><Id>&lol2;</Id></Stmt></BkToCstmrStmt></Document>"""
    with pytest.raises(BankImportError) as exc:
        parse_statement(bomb)
    assert exc.value.code == PARSE_ERROR
    assert "veiligheid" in exc.value.message


def test_camt053_external_entity_is_rejected():
    xxe = b"""<?xml version="1.0"?>
<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<Document><BkToCstmrStmt><Stmt><Id>&x;</Id></Stmt></BkToCstmrStmt></Document>"""
    with pytest.raises(BankImportError):
        parse_statement(xxe)


def test_camt053_malformed_xml():
    with pytest.raises(BankImportError) as exc:
        parse_statement(b"<Document><BkToCstmrStmt><Stmt>")
    assert "beschadigd" in exc.value.message


def test_camt053_entry_without_date_names_the_entry():
    xml = load("camt053_002.xml").replace(b"<BookgDt><Dt>2024-03-02</Dt></BookgDt>", b"")
    with pytest.raises(BankImportError) as exc:
        parse_statement(xml)
    assert "boeking 2" in exc.value.message and "boekingsdatum" in exc.value.message


def test_camt053_split_amounts_must_add_up():
    xml = load("camt053_002.xml").replace(b"<Amt Ccy=\"EUR\">50.00</Amt>", b"<Amt Ccy=\"EUR\">49.00</Amt>")
    with pytest.raises(BankImportError) as exc:
        parse_statement(xml)
    assert "optellen" in exc.value.message


def test_camt053_foreign_currency_refused():
    xml = load("camt053_002.xml").replace(b"<Ccy>EUR</Ccy>", b"<Ccy>USD</Ccy>")
    with pytest.raises(BankImportError) as exc:
        parse_statement(xml)
    assert "USD" in exc.value.message and "euro" in exc.value.message


def test_camt053_without_entries_is_empty():
    xml = b"""<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>
    <Acct><Id><IBAN>NL91ABNA0417164300</IBAN></Id></Acct></Stmt></BkToCstmrStmt></Document>"""
    with pytest.raises(BankImportError) as exc:
        parse_statement(xml)
    assert exc.value.code == EMPTY
    assert exc.value.message == "Er staan geen transacties in dit bestand."


def test_camt053_pending_entries_are_ignored():
    xml = load("camt053_002.xml").replace(b"<Sts>BOOK</Sts>", b"<Sts>PDNG</Sts>", 1)
    assert len(parse_statement(xml).transactions) == 6


# --- MT940 ----------------------------------------------------------------


def test_mt940_ing_golden():
    st = parse_statement(load("mt940_ing.sta"))
    assert (st.format, st.bank, st.account_iban) == ("mt940", "ing", "NL20INGB0001234567")
    assert summary(st) == [
        (date(2024, 3, 1), -1210, "Kantoor BV", "NL02ABNA0123456789", "Factuur 2024-001 kantoorartikelen"),
        (date(2024, 3, 2), 100000, "Klant BV", "NL71INGB0009876543", "Betaling factuur 17"),  # wrapped line
        (date(2024, 3, 4), -350, "Koffiebar", None, "Koffie"),
        (date(2024, 3, 4), -350, "Koffiebar", None, "Koffie"),
        (date(2024, 3, 4), 2000, "Kantoor BV", None, "Terugboeking"),  # RD flips the sign
    ]
    assert (st.opening_cents, st.closing_cents) == (100000, 200090)
    assert_balances(st)
    assert st.transactions[0].end_to_end_id == "E2E-001"
    assert st.transactions[1].end_to_end_id is None


def test_mt940_rabobank_flavour_golden():
    st = parse_statement(load("mt940_rabo.sta"))
    assert (st.bank, st.account_iban) == ("rabobank", "NL44RABO0123456789")
    assert summary(st) == [
        (date(2024, 1, 2), -4500, None, "NL02ABNA0123456789", "NL02ABNA0123456789 ABNANL2A Kantoor BV Factuur 12 januari"),
        (date(2024, 1, 4), 30000, None, "NL71INGB0009876543", "NL71INGB0009876543 INGBNL2A Klant BV Betaling"),
        (date(2024, 1, 5), 9999, "Webshop BV", "NL93RABO0987654321", "Webshop order 123"),
    ]
    assert st.transactions[0].bank_reference == "B01"
    assert (st.opening_cents, st.closing_cents) == (25000, 60499)
    assert_balances(st)


def test_mt940_value_and_booking_date_across_year_end():
    text = (
        b":20:X\n:25:NL20INGB0001234567\n:60F:C231229EUR0,00\n"
        b":61:2312300102C5,00NTRFNONREF\n:86:/TRTP/X/REMI/jaarwisseling\n:62F:C240102EUR5,00\n"
    )
    t = parse_statement(text).transactions[0]
    assert (t.value_date, t.booking_date) == (date(2023, 12, 30), date(2024, 1, 2))


def test_mt940_balance_mismatch_is_visible():
    text = load("mt940_ing.sta").replace(b"EUR2000,90", b"EUR2001,00")
    assert parse_statement(text).balance_difference_cents == 10


def test_mt940_bad_statement_line_names_the_transaction():
    text = load("mt940_ing.sta").replace(b":61:2403020302C1000,00", b":61:2403020302X1000,00")
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert exc.value.code == PARSE_ERROR and "transactie 2" in exc.value.message


def test_mt940_bad_amount_is_rejected():
    text = load("mt940_ing.sta").replace(b"D12,10N", b"D12,105N")
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "geen geldig bedrag" in exc.value.message


def test_mt940_windows_1252_and_bom_and_crlf():
    text = load("mt940_ing.sta").decode().replace("Koffiebar", "Café Zoë")
    for payload in (text.encode("cp1252"), b"\xef\xbb\xbf" + text.encode("utf-8"), text.replace("\n", "\r\n").encode("cp1252")):
        st = parse_statement(payload)
        assert st.transactions[2].counterparty_name == "Café Zoë"
        assert_balances(st)


def test_mt940_foreign_currency_refused():
    text = load("mt940_ing.sta").replace(b":60F:C240229EUR", b":60F:C240229USD")
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "USD" in exc.value.message


# --- CSV ------------------------------------------------------------------

EXPECTED_CSV = [
    (date(2024, 3, 1), -1210, "Kantoor BV", "NL02ABNA0123456789", "Factuur 2024-001"),
    (date(2024, 3, 2), 100000, "Klant BV", "NL71INGB0009876543", "Betaling factuur 17"),
    (date(2024, 3, 4), -350, "Koffiebar", None, "Koffie"),
]


def test_csv_ing_golden():
    st = parse_statement(load("ing.csv"))
    assert (st.format, st.bank, st.account_iban) == ("csv", "ing", "NL20INGB0001234567")
    assert summary(st) == EXPECTED_CSV + [EXPECTED_CSV[2]]  # two identical coffees are kept


def test_csv_ing_comma_delimited_english_headers():
    text = (
        'Date,Name / Description,Account,Counterparty,Code,Debit/credit,Amount (EUR),Transaction type,Notifications\n'
        '20240301,Kantoor BV,NL20INGB0001234567,NL02ABNA0123456789,OV,Debit,"1.234,56",Transfer,Factuur\n'
    )
    st = parse_statement(text.encode())
    assert summary(st) == [(date(2024, 3, 1), -123456, "Kantoor BV", "NL02ABNA0123456789", "Factuur")]


def test_csv_rabobank_golden():
    st = parse_statement(load("rabobank.csv"))
    assert (st.bank, st.account_iban) == ("rabobank", "NL44RABO0123456789")
    assert summary(st) == [
        (date(2024, 3, 1), -1210, "Kantoor BV", "NL02ABNA0123456789", "Factuur 2024-001 kantoorartikelen"),
        EXPECTED_CSV[1],
        EXPECTED_CSV[2],
    ]
    assert [t.balance_after_cents for t in st.transactions] == [98790, 198790, 198440]
    assert [t.bank_reference for t in st.transactions] == ["1", "2", "3"]
    assert st.transactions[0].value_date == date(2024, 3, 1)


def test_csv_rabobank_windows_1252():
    st = parse_statement(load("rabobank.csv").decode().encode("cp1252"))  # "initiërende" has an e-umlaut
    assert st.bank == "rabobank" and len(st.transactions) == 3


def test_csv_abn_amro_tab_golden():
    st = parse_statement(load("abn_amro.tab"))
    assert (st.bank, st.format) == ("abn_amro", "csv")
    assert st.account_iban is None  # numeric rekeningnummer, no IBAN in the file
    assert summary(st) == [
        (date(2024, 3, 1), -1210, "Kantoor BV", "NL02ABNA0123456789", "Factuur 2024-001"),
        EXPECTED_CSV[1],
        (date(2024, 3, 4), -350, None, None, "BEA NR:XX1234 04.03.24/10.15 Koffiebar Utrecht,PAS123"),
    ]
    assert st.transactions[1].end_to_end_id == "K-9"
    assert [t.balance_after_cents for t in st.transactions] == [98790, 198790, 198440]


def test_csv_abn_amro_with_header_row():
    text = "Rekeningnummer\tMuntsoort\tTransactiedatum\tBeginsaldo\tEindsaldo\tRentedatum\tTransactiebedrag\tOmschrijving\n"
    text += "123456789\tEUR\t20240301\t10,00\t7,50\t20240301\t-2,50\tKoffie\n"
    st = parse_statement(text.encode())
    assert summary(st) == [(date(2024, 3, 1), -250, None, None, "Koffie")]


def test_csv_bunq_golden():
    st = parse_statement(load("bunq.csv"))
    assert (st.bank, st.account_iban) == ("bunq", "NL23BUNQ2025123456")
    assert summary(st) == EXPECTED_CSV


def test_csv_without_account_column_has_no_account_iban():
    text = "Date,Amount,Counterparty,Name,Description,Account\n2024-03-01,-1.00,,Foo,Bar,\n"
    assert parse_statement(text.encode()).account_iban is None


def test_csv_utf8_bom_and_wrong_extension():
    st = parse_statement(b"\xef\xbb\xbf" + load("bunq.csv"))
    assert len(st.transactions) == 3


def test_csv_hint_bank_does_not_break_detection():
    assert parse_statement(load("ing.csv"), hint_bank="ing").bank == "ing"
    assert parse_statement(load("ing.csv"), hint_bank="bunq").bank == "ing"


def test_csv_bad_amount_names_the_line():
    text = load("bunq.csv").replace(b"-12.10", b"-12.105")
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert exc.value.code == PARSE_ERROR and "regel 2" in exc.value.message and "-12.105" in exc.value.message


def test_csv_bad_date_names_the_line():
    text = load("ing.csv").replace(b'"20240302"', b'"02-03-2024"')
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "regel 3" in exc.value.message


def test_csv_zero_amount_rejected():
    text = load("bunq.csv").replace(b"-3.50", b"0.00")
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "0" in exc.value.message and "regel 4" in exc.value.message


def test_csv_unknown_af_bij_value():
    text = load("ing.csv").replace(b'"Af";"12,10"', b'"Foo";"12,10"')
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "Af/Bij" in exc.value.message


def test_csv_foreign_currency_refused():
    text = load("rabobank.csv").replace(b'"EUR"', b'"USD"')
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "USD" in exc.value.message


def test_csv_two_accounts_refused():
    text = load("bunq.csv").replace(b"2024-03-04,-3.50,NL23BUNQ2025123456", b"2024-03-04,-3.50,NL20INGB0001234567")
    with pytest.raises(BankImportError) as exc:
        parse_statement(text)
    assert "meerdere rekeningen" in exc.value.message


def test_csv_header_only_is_empty():
    header = load("bunq.csv").splitlines()[0]
    with pytest.raises(BankImportError) as exc:
        parse_statement(header + b"\n")
    assert exc.value.code == EMPTY


# --- general detection / refusal -----------------------------------------


def test_unknown_csv_header_gives_actionable_message():
    with pytest.raises(BankImportError) as exc:
        parse_statement(b"a;b;c\n1;2;3\n")
    assert exc.value.code == UNKNOWN_FORMAT
    assert "CAMT.053" in exc.value.message and "ING, Rabobank, ABN AMRO of bunq" in exc.value.message


@pytest.mark.parametrize(
    "content",
    [b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", b"<html><body>Inloggen</body></html>"],
)
def test_non_statement_files_are_refused(content):
    with pytest.raises(BankImportError) as exc:
        parse_statement(content)
    assert exc.value.code == UNKNOWN_FORMAT


def test_pdf_message_mentions_pdf():
    with pytest.raises(BankImportError) as exc:
        parse_statement(b"%PDF-1.4 blah")
    assert "PDF" in exc.value.message


def test_empty_file():
    with pytest.raises(BankImportError) as exc:
        parse_statement(b"  \n")
    assert exc.value.code == EMPTY


def test_file_too_big():
    with pytest.raises(BankImportError) as exc:
        parse_statement(b"x" * (10 * 1024 * 1024 + 1))
    assert exc.value.code == FILE_TOO_BIG


def test_format_description():
    assert format_description(parse_statement(load("camt053_008.xml"))) == "CAMT.053-bestand van ING"
    assert format_description(parse_statement(load("rabobank.csv"))) == "CSV-export van Rabobank"


@pytest.mark.parametrize(
    "name", ["camt053_002.xml", "camt053_008.xml", "mt940_ing.sta", "mt940_rabo.sta", "ing.csv", "rabobank.csv", "abn_amro.tab", "bunq.csv"]
)
def test_all_amounts_are_non_zero_ints(name):
    for t in parse_statement(load(name)).transactions:
        assert type(t.amount_cents) is int and t.amount_cents != 0
        assert t.currency == "EUR" and t.raw
        assert t.description == " ".join(t.description.split())
