"""Pure beginbalans rules: signs, posten, eigen vermogen, validation messages (no DB)."""

from datetime import date

import pytest

from app.domain.ledger import validate_entry
from app.domain.opening.build import (
    AccountRef,
    OpeningInput,
    OpeningItemInput,
    SystemIds,
    build_entry,
    check_input,
    summarize,
)
from app.domain.opening.errors import OpeningError

START = date(2025, 1, 1)
BANK = AccountRef(1, "1210", "Bank", "asset")
AFSCHR = AccountRef(2, "0190", "Cumulatieve afschrijvingen", "asset")
LENING = AccountRef(3, "3600", "Lening bank", "liability")
BTW = AccountRef(4, "3150", "BTW rekening-courant (Belastingdienst)", "liability")
ALLOWED = {a.id: a for a in (BANK, AFSCHR, LENING, BTW)}
SYS = SystemIds(debtors=13, creditors=30, equity=20)
NAMES = {7: "Jansen", 8: "Bol B.V."}


def deb(number="V-1", amount=10000, contact=7, day=date(2024, 12, 1), due=None):
    return OpeningItemInput("debiteur", contact, number, day, due, amount)


def cred(number="I-1", amount=5000, contact=8, day=date(2024, 12, 5), due=None):
    return OpeningItemInput("crediteur", contact, number, day, due, amount)


def build(balances=(), items=()):
    entry = build_entry(
        OpeningInput(list(balances), list(items)), ALLOWED, SYS, 99, 2025, START, NAMES
    )
    validate_entry(entry)
    return entry


def lines(entry):
    return [(l.account_id, l.debit_cents, l.credit_cents) for l in entry.lines]


# --- lines -------------------------------------------------------------------------------
def test_asset_positive_is_debit_and_equity_credit():
    entry = build([(BANK.id, 125000)])
    assert lines(entry) == [(BANK.id, 125000, 0), (SYS.equity, 0, 125000)]
    assert entry.kind == "opening" and entry.journal_id == 99
    assert entry.booking_date == START and entry.description == "Beginbalans 2025"
    assert entry.reference is None


def test_asset_negative_is_credit():
    entry = build([(BANK.id, 100000), (AFSCHR.id, -30000)])
    assert lines(entry) == [(AFSCHR.id, 0, 30000), (BANK.id, 100000, 0), (SYS.equity, 0, 70000)]


def test_liability_positive_credit_negative_debit():
    entry = build([(BANK.id, 50000), (LENING.id, 20000), (BTW.id, -1000)])
    assert lines(entry) == [
        (BANK.id, 50000, 0),
        (BTW.id, 1000, 0),
        (LENING.id, 0, 20000),
        (SYS.equity, 0, 31000),
    ]


def test_bank_overdrawn_gives_negative_equity_debit():
    entry = build([(BANK.id, -5000)])
    assert lines(entry) == [(BANK.id, 0, 5000), (SYS.equity, 5000, 0)]


def test_debiteur_and_crediteur_posten():
    entry = build(items=[deb("V-1", 10000), deb("V-2", 2500), cred("I-1", 5000)])
    assert lines(entry) == [
        (SYS.debtors, 10000, 0),
        (SYS.debtors, 2500, 0),
        (SYS.creditors, 0, 5000),
        (SYS.equity, 0, 7500),
    ]
    assert [l.description for l in entry.lines[:3]] == ["Jansen - V-1", "Jansen - V-2", "Bol B.V. - I-1"]


def test_no_equity_line_when_balanced():
    entry = build([(BANK.id, 5000)], [cred("I-1", 5000)])
    assert lines(entry) == [(BANK.id, 5000, 0), (SYS.creditors, 0, 5000)]


def test_zero_balances_are_skipped():
    entry = build([(BANK.id, 0), (LENING.id, 0), (AFSCHR.id, 100)])
    assert lines(entry) == [(AFSCHR.id, 100, 0), (SYS.equity, 0, 100)]


def test_no_vat_code_and_balanced_by_construction():
    entry = build(
        [(BANK.id, 123456), (AFSCHR.id, -777), (LENING.id, 99999), (BTW.id, -3)],
        [deb(amount=1), cred(amount=987654)],
    )
    assert all(l.vat_code is None for l in entry.lines)
    assert sum(l.debit_cents for l in entry.lines) == sum(l.credit_cents for l in entry.lines)


def test_invoice_number_is_trimmed_in_description():
    entry = build(items=[deb("  V-9 ")])
    assert entry.lines[0].description == "Jansen - V-9"


# --- summary -----------------------------------------------------------------------------
def test_summarize_totals_and_negative_warning():
    s = summarize(OpeningInput([(BANK.id, 10000), (LENING.id, 4000)], [deb(amount=500), cred(amount=100)]), ALLOWED)
    assert (s.assets_cents, s.liabilities_cents, s.equity_cents) == (10500, 4100, 6400)
    assert s.warnings == []
    neg = summarize(OpeningInput([(LENING.id, 4000)], []), ALLOWED)
    assert neg.equity_cents == -4000
    assert neg.warnings == [
        "Je schulden zijn hoger dan je bezittingen; je eigen vermogen is negatief. Klopt dat?"
    ]


def test_summarize_ignores_incomplete_rows():
    s = summarize(
        OpeningInput([(BANK.id, 100), (999, 5000)], [deb(amount=0), cred(amount=-5), cred(contact=None, amount=300)]),
        ALLOWED,
    )
    assert (s.assets_cents, s.liabilities_cents, s.equity_cents) == (100, 300, -200)


# --- validation --------------------------------------------------------------------------
def check(balances=(), items=(), **kw):
    check_input(OpeningInput(list(balances), list(items)), ALLOWED, START, contact_names=NAMES, **kw)


def message(balances=(), items=(), **kw):
    with pytest.raises(OpeningError) as exc:
        check(balances, items, **kw)
    return exc.value


def test_valid_input_passes():
    check([(BANK.id, 100)], [deb(), cred(due=date(2025, 1, 31))])


@pytest.mark.parametrize("balances", [[], [(BANK.id, 0)]])
def test_empty(balances):
    err = message(balances)
    assert err.code == "EMPTY"
    assert err.message == "Vul minstens één bedrag of openstaande factuur in."


@pytest.mark.parametrize(
    "ref",
    [
        AccountRef(13, "1300", "Debiteuren", "asset"),
        AccountRef(30, "3000", "Crediteuren", "liability"),
        AccountRef(20, "2000", "Ondernemingsvermogen / Kapitaal", "equity"),
    ],
)
def test_account_not_allowed(ref):
    err = message([(ref.id, 100)], account_labels={ref.id: ref})
    assert err.code == "ACCOUNT_NOT_ALLOWED"
    assert err.message == (
        f"Rekening {ref.code} {ref.name} hoort niet in de beginbalans. "
        "Kies een rekening voor bezittingen of schulden."
    )


def test_account_not_allowed_without_label():
    err = message([(555, 100)])
    assert err.message.startswith("Deze rekening hoort niet in de beginbalans.")


def test_zero_on_not_allowed_account_is_skipped():
    check([(555, 0), (BANK.id, 1)])


@pytest.mark.parametrize(
    "item, text",
    [
        (deb(contact=None), "Kies bij welke relatie deze factuur hoort."),
        (deb(number="   "), "Vul het factuurnummer in."),
        (deb(number="X" * 65), "Het factuurnummer is te lang (maximaal 64 tekens)."),
        (deb(day=None), "Vul de factuurdatum in."),
        (
            deb(day=date(2025, 1, 2)),
            "De factuurdatum ligt na de startdatum van je administratie. "
            "Boek deze factuur gewoon via de Inbox of Verkoop.",
        ),
        (
            deb(day=date(2024, 12, 1), due=date(2024, 11, 30)),
            "De vervaldatum ligt vóór de factuurdatum. Controleer beide datums.",
        ),
        (
            deb(amount=0),
            "Vul een bedrag groter dan nul in. Een openstaande creditnota trek je af van "
            "een andere factuur van dezelfde relatie.",
        ),
        (deb(amount=-100), "Vul een bedrag groter dan nul in."),
    ],
)
def test_item_messages(item, text):
    err = message([(BANK.id, 1)], [cred(), item])
    assert err.code == "INVALID_ITEM"
    assert err.message.startswith("Openstaande factuur 1 (klanten): ")
    assert text in err.message


def test_item_row_number_counts_per_side():
    err = message(items=[deb(), cred(), cred("I-2", amount=0)])
    assert err.message.startswith("Openstaande factuur 2 (leveranciers): ")


def test_invoice_date_on_start_date_and_64_chars_allowed():
    check(items=[deb(number="X" * 64, day=START, due=START)])


def test_invalid_side():
    err = message(items=[OpeningItemInput("klant", 7, "A", START, None, 1)])
    assert err.code == "INVALID_ITEM"


def test_duplicate_item():
    err = message(items=[deb("V-1"), deb(" v-1 ")])
    assert err.code == "DUPLICATE_ITEM"
    assert err.message == "Factuur v-1 van Jansen staat er twee keer in."


def test_same_number_other_side_or_contact_is_fine():
    check(items=[deb("A-1"), cred("A-1"), deb("A-1", contact=8)])


def test_amounts_must_be_int():
    with pytest.raises(TypeError):
        check([(BANK.id, 1.5)])
