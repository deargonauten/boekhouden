"""Parsing and validating the nakijken form (pure, no database)."""

from datetime import date

import pytest

from app.domain.errors import ReviewValidationError
from app.domain.extraction.review import ReviewInput, ReviewLineInput, parse_review
from app.domain.extraction.suggestions import AccountRef

ACCOUNTS = [AccountRef("4625", "expense"), AccountRef("1210", "asset")]
VAT = {"NL_21": 2100, "NL_9": 900}


def form(**kw) -> ReviewInput:
    base = dict(
        supplier_name="Bol B.V.",
        invoice_number="F-1",
        invoice_date="21-10-2026",
        total_excl="100,00",
        total_vat="21,00",
        total_incl="121,00",
        lines=[ReviewLineInput("Papier", "100,00", "NL_21", "21,00", "4625")],
    )
    base.update(kw)
    return ReviewInput(**base)


def parse(data, finish=False):
    return parse_review(data, accounts=ACCOUNTS, vat_codes=VAT, finish=finish)


def errors_of(data, finish=False) -> ReviewValidationError:
    with pytest.raises(ReviewValidationError) as exc:
        parse(data, finish)
    return exc.value


def test_happy_path_converts_everything_to_typed_values():
    p = parse(form(due_date="2026-11-20", supplier_kvk="1234 5678", supplier_iban="nl91 abna 0417 1643 00"))
    assert p.invoice_date == date(2026, 10, 21)
    assert p.due_date == date(2026, 11, 20)
    assert (p.total_excl_cents, p.total_vat_cents, p.total_incl_cents) == (10000, 2100, 12100)
    assert p.supplier_kvk == "12345678"
    assert p.supplier_iban == "NL91ABNA0417164300"
    (line,) = p.lines
    assert (line.amount_excl_cents, line.vat_amount_cents) == (10000, 2100)
    assert (line.vat_code, line.account_code) == ("NL_21", "4625")


def test_amounts_are_ints_never_floats():
    p = parse(form(total_excl="1.234,56"))
    assert p.total_excl_cents == 123456 and type(p.total_excl_cents) is int


def test_blank_values_become_none_and_empty_lines_are_dropped():
    p = parse(
        form(
            invoice_date="",
            total_excl=" ",
            lines=[ReviewLineInput(), ReviewLineInput("x", "5,00", "", "", "")],
        )
    )
    assert p.invoice_date is None and p.total_excl_cents is None
    assert len(p.lines) == 1 and p.lines[0].vat_code is None and p.lines[0].account_code is None


def test_bad_amount_message_is_plain_dutch_and_names_the_field():
    err = errors_of(form(total_excl="abc"))
    assert "'abc' is geen geldig bedrag. Schrijf bijvoorbeeld 1.234,56" in err.messages[0]
    assert "total_excl" in err.fields


def test_bad_line_amount_names_the_line():
    err = errors_of(form(lines=[ReviewLineInput("a", "1,00"), ReviewLineInput("b", "x,y")]))
    assert "Regel 2" in err.messages[0]
    assert "line.1.amount" in err.fields


def test_dates_accept_dutch_and_iso_and_reject_the_rest():
    assert parse(form(invoice_date="1-2-2026")).invoice_date == date(2026, 2, 1)
    assert parse(form(invoice_date="2026-02-01")).invoice_date == date(2026, 2, 1)
    err = errors_of(form(invoice_date="31-02-2026"))
    assert "31-02-2026" in err.messages[0] and "dd-mm-jjjj" in err.messages[0]
    assert errors_of(form(due_date="morgen")).fields.keys() == {"due_date"}


def test_unknown_vat_code_and_bad_account():
    err = errors_of(
        form(lines=[ReviewLineInput("a", "1,00", "BTW99", "", "4625"), ReviewLineInput("b", "1,00", "", "", "1210")])
    )
    assert len(err.messages) == 2
    assert "BTW99" in err.messages[0]
    assert "1210" in err.messages[1]
    assert set(err.fields) == {"line.0.vat_code", "line.1.account"}


def test_invalid_identifiers_use_relation_messages():
    err = errors_of(form(supplier_kvk="12", supplier_btw_number="X", supplier_iban="NL00"))
    assert set(err.fields) == {"supplier_kvk", "supplier_btw_number", "supplier_iban"}
    assert any("KvK" in m for m in err.messages)


def test_all_problems_are_reported_at_once():
    err = errors_of(form(total_excl="abc", invoice_date="nee", supplier_kvk="1"))
    assert len(err.messages) == 3


def test_unknown_kind_and_currency():
    assert "kind" in errors_of(form(kind="spam")).fields
    assert "currency" in errors_of(form(currency="EURO")).fields
    assert parse(form(currency=" usd ")).currency == "USD"
    assert parse(form(currency="")).currency == "EUR"


# --- finish ---------------------------------------------------------------------
def test_finish_requires_name_date_and_a_line_with_amount():
    err = errors_of(form(supplier_name="", invoice_date="", lines=[ReviewLineInput("x")]), finish=True)
    assert set(err.fields) >= {"supplier_name", "invoice_date", "lines"}


def test_finish_requires_lines_to_match_total():
    err = errors_of(form(total_excl="110,00"), finish=True)
    assert err.messages == [
        "De regels tellen op tot € 100,00, maar het totaal is € 110,00. Pas een regel of het totaal aan."
    ]
    assert "total_excl" in err.fields


def test_finish_accepts_mismatch_when_overridden():
    p = parse(form(total_excl="110,00", totals_override=True), finish=True)
    assert p.totals_override is True


def test_finish_without_total_has_nothing_to_compare():
    parse(form(total_excl="", total_vat="", total_incl=""), finish=True)


def test_mismatch_is_fine_when_not_finishing():
    parse(form(total_excl="110,00"))


# --- foreign currency and verlegde btw ---------------------------------------------------
def test_exchange_rate_and_shifted_rate_are_parsed():
    p = parse(form(currency="USD", exchange_rate="1,0842", shifted_vat_rate="9"))
    assert p.exchange_rate_micro == 1_084_200
    assert p.shifted_vat_rate_bp == 900


def test_blank_rates_are_none():
    p = parse(form())
    assert p.exchange_rate_micro is None and p.shifted_vat_rate_bp is None


def test_bad_exchange_rate_is_reported():
    err = errors_of(form(currency="USD", exchange_rate="veel"))
    assert "exchange_rate" in err.fields and "wisselkoers" in err.fields["exchange_rate"].lower()


def test_bad_shifted_rate_is_reported():
    assert "shifted_vat_rate" in errors_of(form(shifted_vat_rate="abc")).fields


def test_finish_requires_exchange_rate_for_foreign_currency():
    err = errors_of(form(currency="USD"), finish=True)
    assert "exchange_rate" in err.fields and "USD" in err.fields["exchange_rate"]
    assert parse(form(currency="USD", exchange_rate="1,25"), finish=True).exchange_rate_micro == 1_250_000
    assert parse(form(currency="EUR"), finish=True).exchange_rate_micro is None


def test_euro_invoice_drops_a_leftover_exchange_rate():
    assert parse(form(currency="EUR", exchange_rate="1,25")).exchange_rate_micro is None
