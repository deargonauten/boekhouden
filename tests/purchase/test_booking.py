"""Pure booking rules: check_bookable, build_entry, preview_lines (no database)."""

from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.ledger import validate_entry
from app.domain.purchase.booking import (
    AccountIds,
    BookingInput,
    BookingLineInput,
    booking_kind,
    build_entry,
    check_bookable,
    invoice_number_key,
    preview_lines,
)
from app.domain.purchase.errors import (
    ALREADY_BOOKED,
    INVALID_TOTALS,
    MISSING_FIELD,
    NOT_REVIEWED,
    UNSUPPORTED_VAT,
    ZERO_AMOUNT,
    BookingError,
)

ACC = AccountIds(creditors=300, vat_receivable=140)
COSTS, OTHER = 420, 430
RUBRIEKEN = {
    "GEEN": None,
    "NL_21": "5b",
    "NL_9": "5b",
    "NL_0": None,
    "VERLEGD": "2a",
    "EU_GOEDEREN": "4b",
    "EU_DIENSTEN": "4b",
    "EXPORT": "4a",
}


def line(amount=10000, vat=2100, code="NL_21", account=COSTS, description="Papier"):
    return BookingLineInput(
        description=description,
        account_id=account,
        vat_code=code,
        amount_excl_cents=amount,
        vat_amount_cents=vat,
    )


def inp(*lines, **kw) -> BookingInput:
    lines = lines or (line(),)
    excl = sum(l.amount_excl_cents or 0 for l in lines)
    vat = sum(l.vat_amount_cents or 0 for l in lines)
    base = dict(
        supplier_name="Bol B.V.",
        contact_id=7,
        invoice_number="F-1",
        invoice_date=date(2025, 3, 10),
        lines=tuple(lines),
        total_excl_cents=excl,
        total_vat_cents=vat,
        total_incl_cents=excl + vat,
        vat_purchase_rubrieken=RUBRIEKEN,
    )
    base.update(kw)
    return BookingInput(**base)


def side(entry, account):
    """(debit, credit) totals on an account."""
    d = sum(l.debit_cents for l in entry.lines if l.account_id == account)
    c = sum(l.credit_cents for l in entry.lines if l.account_id == account)
    return d, c


# --- build_entry: invoice ------------------------------------------------------------
def test_single_line_invoice():
    entry = build_entry(inp(), ACC, journal_id=5)
    validate_entry(entry)
    assert entry.journal_id == 5
    assert entry.booking_date == date(2025, 3, 10)
    assert entry.reference == "F-1"
    assert entry.description == "Bol B.V. - F-1"
    assert entry.kind == "normal"
    assert [(l.account_id, l.debit_cents, l.credit_cents, l.vat_code) for l in entry.lines] == [
        (COSTS, 10000, 0, "NL_21"),
        (140, 2100, 0, None),
        (300, 0, 12100, None),
    ]


def test_many_lines_mixed_rates_one_vat_line_per_code():
    lines = (
        line(10000, 2100, "NL_21"),
        line(5000, 450, "NL_9", account=OTHER),
        line(2000, 420, "NL_21", account=OTHER),
        line(3000, 0, "NL_0"),
    )
    entry = build_entry(inp(*lines), ACC, journal_id=5)
    validate_entry(entry)
    expense = [l for l in entry.lines if l.account_id in (COSTS, OTHER)]
    assert [(l.debit_cents, l.vat_code) for l in expense] == [
        (10000, "NL_21"),
        (5000, "NL_9"),
        (2000, "NL_21"),
        (3000, "NL_0"),
    ]
    vat_lines = [l for l in entry.lines if l.account_id == 140]
    assert [(l.debit_cents, l.vat_code) for l in vat_lines] == [(2520, None), (450, None)]
    assert side(entry, 300) == (0, 22970)
    assert sum(l.debit_cents for l in entry.lines) == sum(l.credit_cents for l in entry.lines)


def test_printed_vat_is_used_never_recomputed():
    # 21% of 3,33 is 0,70 (rounded); the invoice printed 0,69: the invoice is the truth.
    entry = build_entry(inp(line(333, 69)), ACC, journal_id=1)
    assert side(entry, 140) == (69, 0)
    assert side(entry, 300) == (0, 402)


def test_no_vat_line_when_vat_is_zero():
    entry = build_entry(inp(line(5000, 0, "NL_0")), ACC, journal_id=1)
    assert [l.account_id for l in entry.lines] == [COSTS, 300]
    validate_entry(entry)


def test_negative_discount_line_goes_to_the_other_side():
    lines = (line(10000, 2100), line(-1000, -210, description="Korting"))
    entry = build_entry(inp(*lines), ACC, journal_id=1)
    validate_entry(entry)
    assert side(entry, COSTS) == (10000, 1000)
    assert side(entry, 140) == (1890, 0)
    assert side(entry, 300) == (0, 10890)


def test_description_is_truncated_to_255():
    entry = build_entry(inp(supplier_name="X" * 300), ACC, journal_id=1)
    assert len(entry.description) == 255
    validate_entry(entry)


def test_invoice_number_is_trimmed():
    entry = build_entry(inp(invoice_number="  F-9 "), ACC, journal_id=1)
    assert entry.reference == "F-9"
    assert entry.description == "Bol B.V. - F-9"


# --- build_entry: credit note --------------------------------------------------------
def test_credit_note_swaps_debit_and_credit():
    lines = (line(10000, 2100), line(5000, 450, "NL_9"))
    entry = build_entry(inp(*lines, kind="credit_note"), ACC, journal_id=1)
    validate_entry(entry)
    assert side(entry, COSTS) == (0, 15000)
    assert side(entry, 140) == (0, 2550)
    assert side(entry, 300) == (17550, 0)
    # amounts stay positive
    assert all(l.debit_cents >= 0 and l.credit_cents >= 0 for l in entry.lines)


@pytest.mark.parametrize(
    "kind, expected",
    [("invoice", "invoice"), ("credit_note", "credit_note"), ("receipt", "invoice"), ("unknown", "invoice"), (None, "invoice")],
)
def test_booking_kind(kind, expected):
    assert booking_kind(kind) == expected


def test_invoice_number_key():
    assert invoice_number_key("  F-2025-01A ") == "f-2025-01a"


# --- check_bookable -------------------------------------------------------------------
def test_valid_input_passes():
    check_bookable(inp())


def raises(data, code, *fragments, field=None):
    with pytest.raises(BookingError) as exc:
        check_bookable(data)
    err = exc.value
    assert isinstance(err, LedgerError)
    assert err.code == code
    for fragment in fragments:
        assert fragment in err.message
    if field is not None:
        assert err.field == field
    return err


def test_already_booked():
    raises(inp(already_booked=True), ALREADY_BOOKED, "Dit document is al geboekt")


def test_not_reviewed():
    raises(inp(reviewed=False), NOT_REVIEWED, "nagekeken")


def test_failed_extraction_counts_as_not_reviewed():
    raises(inp(extraction_ok=False), NOT_REVIEWED, "nagekeken")


def test_missing_supplier():
    raises(inp(contact_id=None), MISSING_FIELD, "leverancier", field="supplier_name")


def test_missing_invoice_date():
    raises(inp(invoice_date=None), MISSING_FIELD, "factuurdatum", field="invoice_date")


@pytest.mark.parametrize("number", [None, "", "   "])
def test_missing_invoice_number(number):
    raises(inp(invoice_number=number), MISSING_FIELD, "factuurnummer", field="invoice_number")


def test_no_lines():
    data = inp(lines=(), total_excl_cents=0, total_vat_cents=0, total_incl_cents=100)
    raises(data, MISSING_FIELD, "regel", field="lines")


def test_line_without_account():
    data = inp(line(), line(account=None))
    raises(data, MISSING_FIELD, "Kies bij regel 2 een rekening voor de kosten.", field="line.1.account")


def test_line_without_vat_code():
    raises(inp(line(code=None)), MISSING_FIELD, "regel 1", "BTW-tarief", field="line.0.vat_code")


def test_line_without_amount():
    data = inp(line(amount=None), total_excl_cents=10000, total_incl_cents=12100)
    raises(data, MISSING_FIELD, "regel 1", "bedrag zonder BTW", field="line.0.amount")


def test_line_without_vat_amount():
    data = inp(line(vat=None), total_vat_cents=2100, total_incl_cents=12100)
    raises(data, MISSING_FIELD, "regel 1", "BTW-bedrag", field="line.0.vat_amount")


def test_zero_amount_line():
    data = inp(line(), line(0, 0))
    raises(data, ZERO_AMOUNT, "Regel 2", "€ 0,00", field="line.1.amount")


def test_float_amounts_are_refused():
    with pytest.raises(TypeError):
        check_bookable(inp(line(amount=100.0, vat=21)))


def test_rubriek_outside_purchase_is_refused():
    data = inp(line(10000, 0, "MIJN_X"), vat_purchase_rubrieken={**RUBRIEKEN, "MIJN_X": "3b"})
    raises(data, UNSUPPORTED_VAT, field="line.0.vat_code")


def test_custom_5b_code_is_supported():
    data = inp(line(10000, 2100, "MIJN_21"), vat_purchase_rubrieken={**RUBRIEKEN, "MIJN_21": "5b"})
    check_bookable(data)


def test_lines_do_not_add_up_to_total_excl():
    err = raises(inp(total_excl_cents=11000, total_incl_cents=13100), INVALID_TOTALS, "€ 100,00", "€ 110,00")
    assert err.field == "total_excl"


def test_vat_lines_do_not_add_up_to_total_vat():
    raises(inp(total_vat_cents=2000, total_incl_cents=12000), INVALID_TOTALS, "€ 21,00", "€ 20,00", field="total_vat")


def test_excl_plus_vat_is_not_total_incl():
    raises(inp(total_incl_cents=12000), INVALID_TOTALS, "€ 121,00", "€ 120,00", field="total_incl")


@pytest.mark.parametrize("field_name", ["total_excl_cents", "total_vat_cents", "total_incl_cents"])
def test_missing_totals(field_name):
    raises(inp(**{field_name: None}), MISSING_FIELD)


def test_total_must_be_positive():
    lines = (line(-1000, -210),)
    raises(inp(*lines), INVALID_TOTALS, "groter zijn dan € 0,00")


def test_build_entry_runs_the_content_checks():
    with pytest.raises(BookingError):
        build_entry(inp(line(account=None)), ACC, journal_id=1)


def test_messages_are_plain_dutch_without_codes():
    for data in [inp(contact_id=None), inp(line(account=None)), inp(total_incl_cents=1)]:
        with pytest.raises(BookingError) as exc:
            check_bookable(data)
        assert "_" not in exc.value.message
        assert exc.value.message.endswith(".")


# --- preview_lines ----------------------------------------------------------------------
NAMES = {COSTS: ("4625", "Kantoorkosten"), OTHER: ("4405", "Autokosten"), 140: ("1400", "BTW voorbelasting"), 300: ("3000", "Crediteuren")}
VAT_LABELS = {"NL_21": "21%", "NL_9": "9%", "NL_0": "0%"}


def test_preview_rows_and_summary():
    table = preview_lines(inp(line(10000, 2100)), ACC, NAMES, VAT_LABELS)
    assert [(r.account_code, r.amount_cents, r.side, r.term) for r in table.rows] == [
        ("4625", 10000, "debet", None),
        ("1400", 2100, "debet", "voorbelasting"),
        ("3000", 12100, "credit", "crediteuren"),
    ]
    assert table.rows[0].label == "Kosten"
    assert table.rows[0].description == "Papier"
    assert table.rows[0].vat_label == "21%"
    assert table.rows[1].label == "BTW die je terugkrijgt"
    assert table.rows[2].label == "Nog te betalen aan Bol B.V."
    assert table.summary == "Kosten € 100,00, BTW € 21,00, nog te betalen aan Bol B.V. € 121,00."
    assert table.total_to_pay_cents == 12100


def test_preview_summary_without_vat():
    table = preview_lines(inp(line(5000, 0, "NL_0")), ACC, NAMES, VAT_LABELS)
    assert table.summary == "Kosten € 50,00, geen BTW, nog te betalen aan Bol B.V. € 50,00."


def test_preview_credit_note():
    table = preview_lines(inp(line(10000, 2100), kind="credit_note"), ACC, NAMES, VAT_LABELS)
    assert [r.side for r in table.rows] == ["credit", "credit", "debet"]
    assert table.rows[2].label == "Krijg je terug van Bol B.V."
    assert table.summary == (
        "Creditnota van Bol B.V.: kosten € 100,00 minder, BTW € 21,00 minder terug, "
        "je krijgt € 121,00 terug."
    )
    assert table.total_to_pay_cents == -12100


def test_preview_matches_build_entry():
    lines = (line(10000, 2100), line(5000, 450, "NL_9", account=OTHER))
    data = inp(*lines)
    entry = build_entry(data, ACC, journal_id=1)
    table = preview_lines(data, ACC, NAMES, VAT_LABELS)
    assert [(r.amount_cents, r.side) for r in table.rows] == [
        (l.debit_cents or l.credit_cents, "debet" if l.debit_cents else "credit") for l in entry.lines
    ]

