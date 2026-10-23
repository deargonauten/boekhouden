"""Deterministic checks on extracted invoices (money/VAT: written first)."""

from dataclasses import replace
from datetime import date

import pytest

from app.domain.extraction.suggestions import (
    AccountRef,
    half_up_vat,
    infer_vat_code,
    resolve_account_code,
)
from app.domain.extraction.types import ExtractedInvoice, ExtractedLine
from app.domain.extraction.validation import Flag, assess, flagged_fields
from app.domain.relations import ExtractedContact

TODAY = date(2026, 10, 21)
VAT = {"GEEN": 0, "NL_21": 2100, "NL_9": 900, "NL_0": 0, "VERLEGD": 0}
ACCOUNTS = [
    AccountRef("4625", "expense"),
    AccountRef("4999", "expense"),
    AccountRef("4405", "expense", is_active=False),
    AccountRef("4835", "expense", is_postable=False),
    AccountRef("1210", "asset"),
]
SUPPLIER = ExtractedContact(
    name="Bol B.V.", kvk="12345678", btw_number="NL123456789B01", iban="NL91ABNA0417164300"
)


def good(**kw) -> ExtractedInvoice:
    base = dict(
        supplier=SUPPLIER,
        invoice_number="F-1",
        invoice_date=date(2026, 10, 1),
        total_excl_cents=10000,
        total_vat_cents=2100,
        total_incl_cents=12100,
        lines=(
            ExtractedLine(
                description="Papier",
                amount_excl_cents=10000,
                vat_code="NL_21",
                vat_amount_cents=2100,
                suggested_account_code="4625",
            ),
        ),
    )
    base.update(kw)
    return ExtractedInvoice(**base)


def run(inv, **kw):
    return assess(inv, kw.get("accounts", ACCOUNTS), kw.get("vat", VAT), TODAY)


def by_field(flags, field):
    return [f for f in flags if f.field == field]


def test_clean_invoice_has_no_flags():
    assert run(good()) == []


# --- half-up VAT arithmetic -------------------------------------------------
@pytest.mark.parametrize(
    "excl,rate,expected",
    [
        (10000, 2100, 2100),
        (1050, 2100, 221),  # 220.5 -> up
        (1050, 900, 95),  # 94.5 -> up
        (1049, 2100, 220),  # 220.29
        (1, 900, 0),
        (6, 900, 1),  # 0.54 -> 1
        (5, 900, 0),  # 0.45
        (0, 2100, 0),
        (12345, 0, 0),
        (-1050, 2100, -220),  # symmetric is not required; half-up = toward +inf
    ],
)
def test_half_up_vat(excl, rate, expected):
    assert half_up_vat(excl, rate) == expected
    assert isinstance(half_up_vat(excl, rate), int)


# --- a. line sum -------------------------------------------------------------
def test_line_sum_differs_from_total():
    inv = good(total_excl_cents=11000, total_incl_cents=13100)
    flags = run(inv)
    f = by_field(flags, "total_excl")
    assert len(f) == 1
    assert f[0].reason == "De regels tellen op tot € 100,00, maar het totaal op de factuur is € 110,00."
    assert f[0].level == "low"


def test_line_sum_ok_with_several_lines():
    lines = (
        ExtractedLine("a", 4000, "NL_21", 840, "4625"),
        ExtractedLine("b", 6000, "NL_21", 1260, "4625"),
    )
    assert run(good(lines=lines)) == []


def test_line_sum_skipped_when_a_line_amount_is_missing():
    lines = (ExtractedLine("a", None, "NL_21", None, "4625"),)
    assert by_field(run(good(lines=lines)), "total_excl") == []


# --- b. BTW arithmetic ---------------------------------------------------------
def test_vat_within_tolerance_is_fine():
    inv = good(
        total_vat_cents=2102,
        total_incl_cents=12102,
        lines=(ExtractedLine("a", 10000, "NL_21", 2102, "4625"),),
    )
    assert by_field(run(inv), "line.0.vat_amount") == []


def test_vat_beyond_tolerance_flags_the_line():
    inv = good(
        total_vat_cents=2103,
        total_incl_cents=12103,
        lines=(ExtractedLine("a", 10000, "NL_21", 2103, "4625"),),
    )
    f = by_field(run(inv), "line.0.vat_amount")
    assert len(f) == 1
    assert "21%" in f[0].reason and "€ 21,00" in f[0].reason and "€ 21,03" in f[0].reason


def test_vat_rounding_boundary_uses_half_up():
    # 21% of 10,50 = 2,205 -> 2,21 ; 2,19 is 2 cents off (ok), 2,18 is 3 off (flag)
    def inv(vat):
        return good(
            total_excl_cents=1050,
            total_vat_cents=vat,
            total_incl_cents=1050 + vat,
            lines=(ExtractedLine("a", 1050, "NL_21", vat, "4625"),),
        )

    assert by_field(run(inv(219)), "line.0.vat_amount") == []
    assert len(by_field(run(inv(218)), "line.0.vat_amount")) == 1


def test_vat_is_checked_per_code_group_not_per_line():
    lines = (
        ExtractedLine("a", 333, "NL_21", 70, "4625"),
        ExtractedLine("b", 333, "NL_21", 70, "4625"),
        ExtractedLine("c", 334, "NL_21", 70, "4625"),
    )  # sum 1000 -> 210 expected, 210 given
    inv = good(total_excl_cents=1000, total_vat_cents=210, total_incl_cents=1210, lines=lines)
    assert run(inv) == []


def test_zero_rate_codes_expect_zero_vat():
    inv = good(
        total_vat_cents=500,
        total_incl_cents=10500,
        lines=(ExtractedLine("a", 10000, "VERLEGD", 500, "4625"),),
    )
    assert len(by_field(run(inv), "line.0.vat_amount")) == 1


def test_vat_check_skipped_when_vat_amount_unknown():
    inv = good(lines=(ExtractedLine("a", 10000, "NL_21", None, "4625"),))
    assert by_field(run(inv), "line.0.vat_amount") == []


# --- c. totals ------------------------------------------------------------------
def test_total_incl_mismatch():
    f = by_field(run(good(total_incl_cents=12000)), "total_incl")
    assert len(f) == 1 and f[0].level == "low"
    assert "€ 121,00" in f[0].reason and "€ 120,00" in f[0].reason


def test_totals_check_needs_all_three():
    assert by_field(run(good(total_incl_cents=None)), "total_incl") == []


# --- d. missing --------------------------------------------------------------
@pytest.mark.parametrize(
    "kw,field",
    [
        (dict(invoice_date=None), "invoice_date"),
        (dict(invoice_number=None), "invoice_number"),
        (dict(supplier=ExtractedContact()), "supplier_name"),
        (dict(supplier=ExtractedContact(name="  ")), "supplier_name"),
    ],
)
def test_missing_fields(kw, field):
    f = by_field(run(good(**kw)), field)
    assert len(f) == 1
    assert f[0].reason.startswith("Niet gevonden op de factuur")


# --- e. dates --------------------------------------------------------------------
@pytest.mark.parametrize(
    "d,flagged",
    [
        (date(2026, 10, 21), False),  # today
        (date(2026, 10, 22), True),  # future
        (date(2025, 10, 21), False),  # exactly one year
        (date(2025, 10, 20), True),  # more than one year
        (date(2025, 10, 22), False),
    ],
)
def test_invoice_date_window(d, flagged):
    f = by_field(run(good(invoice_date=d)), "invoice_date")
    assert bool(f) is flagged
    if flagged:
        assert f[0].level == "medium" and "Controleer de datum" in f[0].reason


# --- f. identifiers ----------------------------------------------------------------
@pytest.mark.parametrize(
    "field,value",
    [("kvk", "123"), ("btw_number", "NL12345"), ("iban", "NL00BANK0000000000")],
)
def test_invalid_identifiers_are_flagged(field, value):
    sup = replace(SUPPLIER, **{field: value})
    f = by_field(run(good(supplier=sup)), f"supplier_{field}")
    assert len(f) == 1 and f[0].level == "low"


def test_absent_identifiers_are_not_flagged():
    sup = ExtractedContact(name="Bol B.V.")
    assert run(good(supplier=sup)) == []


def test_formatted_identifiers_are_accepted():
    sup = replace(SUPPLIER, iban="NL91 ABNA 0417 1643 00", btw_number="nl 1234.56.789 b01")
    assert run(good(supplier=sup)) == []


# --- g. accounts -------------------------------------------------------------------
@pytest.mark.parametrize("code", ["9999", "4405", "4835", "1210"])
def test_unusable_account_is_flagged(code):
    inv = good(lines=(ExtractedLine("a", 10000, "NL_21", 2100, code),))
    f = by_field(run(inv), "line.0.account")
    assert len(f) == 1 and "Kies zelf een rekening" in f[0].reason
    assert resolve_account_code(code, ACCOUNTS) is None


def test_missing_account_is_flagged_too():
    inv = good(lines=(ExtractedLine("a", 10000, "NL_21", 2100, None),))
    assert len(by_field(run(inv), "line.0.account")) == 1


def test_valid_account_resolves():
    assert resolve_account_code("4625", ACCOUNTS) == "4625"
    assert resolve_account_code(None, ACCOUNTS) is None


# --- h. vat codes ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "amount,vat,expected",
    [
        (10000, 2100, "NL_21"),
        (10000, 900, "NL_9"),
        (10000, 0, "NL_0"),
        (1050, 221, "NL_21"),
        (1050, 95, "NL_9"),
    ],
)
def test_infer_vat_code(amount, vat, expected):
    assert infer_vat_code(amount, vat, VAT) == expected


def test_infer_vat_code_unknown():
    assert infer_vat_code(10000, 1234, VAT) is None
    assert infer_vat_code(None, 2100, VAT) is None
    assert infer_vat_code(10000, None, VAT) is None
    assert infer_vat_code(10000, 2100, {"GEEN": 0}) is None  # NL_21 not active


def test_unknown_vat_code_is_inferred_with_medium_flag():
    inv = good(lines=(ExtractedLine("a", 10000, "BTW21", 2100, "4625"),))
    f = by_field(run(inv), "line.0.vat_code")
    assert len(f) == 1
    assert f[0].level == "medium" and "Tarief afgeleid uit het bedrag" in f[0].reason


def test_unknown_vat_code_not_inferable_is_flagged_low():
    inv = good(
        total_vat_cents=1234,
        total_incl_cents=11234,
        lines=(ExtractedLine("a", 10000, "BTW21", 1234, "4625"),),
    )
    f = by_field(run(inv), "line.0.vat_code")
    assert len(f) == 1 and f[0].level == "low"


def test_missing_vat_code_is_flagged():
    inv = good(lines=(ExtractedLine("a", 10000, None, None, "4625"),))
    assert len(by_field(run(inv), "line.0.vat_code")) == 1


def test_inferred_code_is_used_for_group_arithmetic():
    # unknown code, but the amounts say 21% -> inferred NL_21 -> arithmetic is consistent
    inv = good(lines=(ExtractedLine("a", 10000, "BTW21", 2100, "4625"),))
    assert by_field(run(inv), "line.0.vat_amount") == []


# --- i/j. currency and credit notes ----------------------------------------------------
def test_non_euro_currency():
    f = by_field(run(good(currency="USD")), "currency")
    assert len(f) == 1
    assert f[0].reason == "Deze factuur is niet in euro's; bedragen zijn niet omgerekend."


def test_credit_note_is_info():
    f = by_field(run(good(kind="credit_note")), "kind")
    assert len(f) == 1 and f[0].level == "info"
    assert f[0].reason == "Dit is een creditnota"


# --- model confidence ----------------------------------------------------------------------
def test_model_confidence_becomes_flags():
    inv = good(
        confidence={"invoice_number": "medium", "invoice_date": "high", "total_excl_cents": "low"},
        lines=(
            ExtractedLine(
                "a", 10000, "NL_21", 2100, "4625", confidence={"amount_excl_cents": "low"}
            ),
        ),
    )
    flags = run(inv)
    assert by_field(flags, "invoice_number")[0].level == "medium"
    assert by_field(flags, "invoice_date") == []
    assert by_field(flags, "total_excl")[0].level == "low"
    assert by_field(flags, "line.0.amount")[0].level == "low"


def test_flags_are_merged_per_field_with_highest_level():
    inv = good(total_incl_cents=12000, confidence={"total_incl_cents": "medium"})
    f = by_field(run(inv), "total_incl")
    assert len(f) == 1 and f[0].level == "low"
    assert "€ 121,00" in f[0].reason


def test_flagged_fields_counts_distinct_fields_and_ignores_info():
    flags = [
        Flag("a", "low", "x"),
        Flag("b", "medium", "y"),
        Flag("kind", "info", "z"),
    ]
    assert flagged_fields(flags) == ["a", "b"]


# --- robustness -----------------------------------------------------------------------------
def test_empty_extraction_never_raises():
    flags = run(ExtractedInvoice(kind="unknown"))
    fields = {f.field for f in flags}
    assert {"invoice_date", "invoice_number", "supplier_name"} <= fields


def test_none_amounts_everywhere_never_raise():
    inv = good(
        total_excl_cents=None,
        total_vat_cents=None,
        total_incl_cents=None,
        lines=(ExtractedLine(), ExtractedLine(None, None, "NL_21", 5, None)),
    )
    run(inv)
