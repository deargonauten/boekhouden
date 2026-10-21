from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.ledger.entries import NewEntry, NewLine, build_storno, validate_entry


def make_entry(lines=None, **kw):
    if lines is None:
        lines = [NewLine(account_id=1, debit_cents=1000), NewLine(account_id=2, credit_cents=1000)]
    defaults = dict(journal_id=1, booking_date=date(2025, 3, 1), description="Test", lines=lines)
    defaults.update(kw)
    return NewEntry(**defaults)


def code_of(entry):
    with pytest.raises(LedgerError) as exc:
        validate_entry(entry)
    assert exc.value.message
    return exc.value.code


def test_valid_entry_passes():
    assert validate_entry(make_entry()) is None


def test_defaults():
    e = make_entry()
    assert e.kind == "normal" and e.reference is None
    line = NewLine(account_id=1, debit_cents=5)
    assert line.credit_cents == 0 and line.description is None and line.vat_code is None


def test_multi_line_balanced():
    lines = [
        NewLine(1, debit_cents=1210),
        NewLine(2, credit_cents=1000, vat_code="NL_21"),
        NewLine(3, credit_cents=210, vat_code="NL_21"),
    ]
    validate_entry(make_entry(lines))


def test_unbalanced_by_one_cent():
    lines = [NewLine(1, debit_cents=1001), NewLine(2, credit_cents=1000)]
    assert code_of(make_entry(lines)) == "UNBALANCED"


def test_message_is_dutch():
    lines = [NewLine(1, debit_cents=1001), NewLine(2, credit_cents=1000)]
    with pytest.raises(LedgerError) as exc:
        validate_entry(make_entry(lines))
    assert "evenwicht" in exc.value.message


def test_too_few_lines():
    assert code_of(make_entry([NewLine(1, debit_cents=5)])) == "TOO_FEW_LINES"
    assert code_of(make_entry([])) == "TOO_FEW_LINES"


def test_zero_zero_line():
    lines = [NewLine(1), NewLine(2, credit_cents=0, debit_cents=0)]
    assert code_of(make_entry(lines)) == "INVALID_LINE_AMOUNT"


def test_both_sided_line():
    lines = [NewLine(1, debit_cents=5, credit_cents=5), NewLine(2, credit_cents=0, debit_cents=0)]
    assert code_of(make_entry(lines)) == "INVALID_LINE_AMOUNT"


def test_negative_amount():
    lines = [NewLine(1, debit_cents=-5), NewLine(2, credit_cents=-5)]
    assert code_of(make_entry(lines)) == "INVALID_LINE_AMOUNT"


@pytest.mark.parametrize("bad", [1.5, True, "5"])
def test_non_int_amount_type_error(bad):
    lines = [NewLine(1, debit_cents=bad), NewLine(2, credit_cents=5)]
    with pytest.raises(TypeError):
        validate_entry(make_entry(lines))


@pytest.mark.parametrize("desc", ["", "   ", None])
def test_empty_description(desc):
    assert code_of(make_entry(description=desc)) == "INVALID_DESCRIPTION"


def test_description_length():
    validate_entry(make_entry(description="x" * 255))
    assert code_of(make_entry(description="x" * 256)) == "INVALID_DESCRIPTION"


def test_missing_date():
    assert code_of(make_entry(booking_date=None)) == "INVALID_DATE"


def test_invalid_kind():
    assert code_of(make_entry(kind="bogus")) == "INVALID_KIND"


@pytest.mark.parametrize("kind", ["normal", "opening", "storno"])
def test_valid_kinds(kind):
    validate_entry(make_entry(kind=kind))


def test_build_storno_swaps_sides_and_copies():
    lines = [
        NewLine(1, debit_cents=1210, description="a"),
        NewLine(2, credit_cents=1000, vat_code="NL_21", description="b"),
        NewLine(3, credit_cents=210, vat_code="NL_21"),
    ]
    out = build_storno(lines)
    assert [(l.account_id, l.debit_cents, l.credit_cents, l.vat_code, l.description) for l in out] == [
        (1, 0, 1210, None, "a"),
        (2, 1000, 0, "NL_21", "b"),
        (3, 210, 0, "NL_21", None),
    ]
    assert sum(l.debit_cents for l in out) == sum(l.credit_cents for l in lines)
    assert lines[0].debit_cents == 1210  # input untouched
    validate_entry(make_entry(out))
