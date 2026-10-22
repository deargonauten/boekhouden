from datetime import date

import pytest
from sqlalchemy import select

from app.domain.errors import LedgerError
from app.domain.ledger import (
    NewEntry, NewLine, add_account, create_fiscal_year, list_fiscal_years, lock_period,
    post_entry,
)
from app.domain.vat import (
    add_vat_code, list_vat_codes_with_usage, rubriek_for, set_vat_code_active,
    update_vat_code,
)
from app.models import Account, Journal

SEED_ORDER = ["GEEN", "NL_21", "NL_9", "NL_0", "VERLEGD", "EU_GOEDEREN", "EU_DIENSTEN", "EXPORT"]


def err(excinfo, code):
    assert excinfo.value.code == code
    return excinfo.value.message


def new(session, **kw):
    args = dict(code="KOR", name="KOR 0%", rate_percent_text="0", sales_rubriek=None, purchase_rubriek=None)
    args.update(kw)
    return add_vat_code(session, **args)


def aid(session, code):
    return session.scalar(select(Account.id).where(Account.code == code))


def post_line_with_code(session, vat_code, day=date(2025, 3, 10)):
    create_fiscal_year(session, 2025)
    jid = session.scalar(select(Journal.id).where(Journal.code == "MEM"))
    post_entry(session, NewEntry(
        journal_id=jid, booking_date=day, description="t",
        lines=[
            NewLine(aid(session, "4210"), debit_cents=1000, vat_code=vat_code),
            NewLine(aid(session, "1210"), credit_cents=1000),
        ],
    ))
    session.commit()


# --- add ----------------------------------------------------------------
def test_add_ok(session):
    v = new(session, code=" nl_5 ", name=" BTW 5% ", rate_percent_text="5", sales_rubriek="1c", purchase_rubriek="5b")
    assert (v.code, v.name, v.rate_bp, v.is_active, v.is_system) == ("NL_5", "BTW 5%", 500, True, False)
    assert (v.sales_rubriek, v.purchase_rubriek) == ("1c", "5b")


def test_add_with_rate_bp_and_empty_rubrieken(session):
    v = new(session, rate_percent_text=None, rate_bp=650, sales_rubriek="", purchase_rubriek="")
    assert v.rate_bp == 650 and v.sales_rubriek is None and v.purchase_rubriek is None


@pytest.mark.parametrize("code", ["", "A", "ABCDEFGHIJKLM", "KO R", "KOR-1", "KÖR"])
def test_add_bad_code(session, code):
    with pytest.raises(LedgerError) as ei:
        new(session, code=code)
    assert err(ei, "INVALID_VAT_CODE") == (
        "Een btw-code bestaat uit 2 tot 12 hoofdletters, cijfers of liggende streepjes, "
        "bijvoorbeeld KOR of NL_5."
    )


def test_add_duplicate(session):
    with pytest.raises(LedgerError) as ei:
        new(session, code="nl_21")
    assert err(ei, "DUPLICATE_CODE") == "De btw-code NL_21 bestaat al. Kies een andere code."


def test_add_name_required(session):
    with pytest.raises(LedgerError) as ei:
        new(session, name="  ")
    assert err(ei, "INVALID_VAT_CODE") == "Geef de btw-code een naam, bijvoorbeeld 'BTW 6%'."


def test_add_bad_rate(session):
    with pytest.raises(LedgerError) as ei:
        new(session, rate_percent_text="abc")
    assert err(ei, "INVALID_VAT_RATE") == "Vul een percentage tussen 0 en 99,99 in, bijvoorbeeld 21 of 6,5."
    with pytest.raises(LedgerError) as ei:
        new(session, rate_percent_text=None, rate_bp=10000)
    err(ei, "INVALID_VAT_RATE")
    with pytest.raises(LedgerError) as ei:
        new(session, rate_percent_text=None, rate_bp=None)
    err(ei, "INVALID_VAT_RATE")


@pytest.mark.parametrize("kw,bad", [
    (dict(sales_rubriek="5b"), "5b"),      # purchase value on the sales side
    (dict(purchase_rubriek="1a"), "1a"),   # sales value on the purchase side
    (dict(sales_rubriek="9z"), "9z"),
])
def test_add_bad_rubriek(session, kw, bad):
    with pytest.raises(LedgerError) as ei:
        new(session, **kw)
    assert err(ei, "INVALID_RUBRIEK") == (
        f"Rubriek {bad} past hier niet. Kies een rubriek uit de lijst of laat het veld leeg."
    )


# --- update -------------------------------------------------------------
def test_update_custom_and_system(session):
    new(session, code="KOR")
    v = update_vat_code(session, "KOR", name="Kleine ondernemer", sales_rubriek="1e", purchase_rubriek=None)
    assert v.name == "Kleine ondernemer" and v.sales_rubriek == "1e" and v.rate_bp == 0
    s = update_vat_code(session, "NL_21", name="BTW hoog", sales_rubriek="1a", purchase_rubriek="5b")
    assert s.name == "BTW hoog" and s.code == "NL_21" and s.rate_bp == 2100 and s.is_system


def test_update_validation(session):
    with pytest.raises(LedgerError) as ei:
        update_vat_code(session, "NL_21", name="", sales_rubriek="1a", purchase_rubriek="5b")
    err(ei, "INVALID_VAT_CODE")
    with pytest.raises(LedgerError) as ei:
        update_vat_code(session, "NL_21", name="X", sales_rubriek="4a", purchase_rubriek="5b")
    err(ei, "INVALID_RUBRIEK")
    with pytest.raises(LedgerError) as ei:
        update_vat_code(session, "NOPE", name="X", sales_rubriek=None, purchase_rubriek=None)
    err(ei, "INVALID_VAT_CODE")


def test_rubriek_change_locked_period(session):
    post_line_with_code(session, "NL_21")
    # open period: editable
    update_vat_code(session, "NL_21", name="BTW 21%", sales_rubriek="1c", purchase_rubriek="5b")
    lock_period(session, list_fiscal_years(session)[0].periods[2].id)  # March
    session.commit()
    with pytest.raises(LedgerError) as ei:
        update_vat_code(session, "NL_21", name="BTW 21%", sales_rubriek="1a", purchase_rubriek="5b")
    assert err(ei, "VAT_CODE_IN_LOCKED_PERIOD") == (
        "Deze btw-code is al gebruikt in een vergrendelde periode, dus de rubriek kun je niet meer "
        "wijzigen. Maak een nieuwe btw-code aan voor het nieuwe geval."
    )
    # rename without rubriek change stays allowed
    assert update_vat_code(session, "NL_21", name="Hoog tarief", sales_rubriek="1c", purchase_rubriek="5b").name == "Hoog tarief"
    # a code not used in the locked period is unaffected
    update_vat_code(session, "NL_9", name="BTW 9%", sales_rubriek="1c", purchase_rubriek="5b")


def test_rubriek_change_other_period_open(session):
    post_line_with_code(session, "NL_21", day=date(2025, 3, 10))
    lock_period(session, list_fiscal_years(session)[0].periods[0].id)  # January only
    session.commit()
    update_vat_code(session, "NL_21", name="BTW 21%", sales_rubriek="1c", purchase_rubriek="5b")


# --- active -------------------------------------------------------------
def test_toggle_active(session):
    new(session)
    assert set_vat_code_active(session, "KOR", False).is_active is False
    assert set_vat_code_active(session, "KOR", True).is_active is True


def test_geen_cannot_be_deactivated(session):
    with pytest.raises(LedgerError) as ei:
        set_vat_code_active(session, "GEEN", False)
    assert err(ei, "VAT_CODE_SYSTEM") == "'Geen btw' is nodig voor boekingen zonder btw en kan niet worden uitgezet."
    assert set_vat_code_active(session, "GEEN", True).is_active


def test_deactivate_default_refused(session):
    with pytest.raises(LedgerError) as ei:
        set_vat_code_active(session, "NL_21", False)
    msg = err(ei, "VAT_CODE_IS_DEFAULT")
    assert msg.startswith("Je kunt BTW 21% niet uitzetten: het is nog het standaard btw-tarief van rekening")
    assert msg.endswith("Kies eerst bij die rekening een ander tarief.")
    assert "en nog" in msg  # many expense accounts


def test_deactivate_default_names_few_accounts(session):
    new(session, code="X1", name="Eigen")
    add_account(session, code="4777", name="Eigen kosten", type="expense", default_vat_code="X1")
    with pytest.raises(LedgerError) as ei:
        set_vat_code_active(session, "X1", False)
    assert err(ei, "VAT_CODE_IS_DEFAULT") == (
        "Je kunt Eigen niet uitzetten: het is nog het standaard btw-tarief van rekening 4777 Eigen kosten. "
        "Kies eerst bij die rekening een ander tarief."
    )


def test_deactivate_ignores_inactive_accounts(session):
    new(session, code="X1", name="Eigen")
    a = add_account(session, code="4777", name="Eigen kosten", type="expense", default_vat_code="X1")
    a.is_active = False
    session.flush()
    assert set_vat_code_active(session, "X1", False).is_active is False


def test_toggle_unknown(session):
    with pytest.raises(LedgerError) as ei:
        set_vat_code_active(session, "NOPE", False)
    err(ei, "INVALID_VAT_CODE")


# --- listing / lookup ---------------------------------------------------
def test_list_with_usage_order_and_counts(session):
    new(session, code="ZZZ", name="Z")
    new(session, code="AAA", name="A")
    post_line_with_code(session, "NL_21")
    rows = list_vat_codes_with_usage(session)
    assert [r.code for r in rows] == SEED_ORDER + ["AAA", "ZZZ"]
    by = {r.code: r for r in rows}
    assert by["NL_21"].used_count == 1 and by["NL_9"].used_count == 0
    assert by["NL_21"].is_system and not by["AAA"].is_system
    assert (by["NL_21"].rate_bp, by["NL_21"].sales_rubriek, by["NL_21"].purchase_rubriek) == (2100, "1a", "5b")
    assert "4210" in by["NL_21"].default_for and by["GEEN"].default_for
    assert by["AAA"].default_for == [] and by["AAA"].is_active


@pytest.mark.parametrize("code,sales,purchase", [
    ("GEEN", None, None), ("NL_21", "1a", "5b"), ("NL_9", "1b", "5b"), ("NL_0", "1e", None),
    ("VERLEGD", "1e", "2a"), ("EU_GOEDEREN", "3b", "4b"), ("EU_DIENSTEN", "3b", "4b"),
    ("EXPORT", "3a", "4a"),
])
def test_rubriek_for_seeded(session, code, sales, purchase):
    assert rubriek_for(session, code, "sales") == sales
    assert rubriek_for(session, code, "purchase") == purchase


def test_rubriek_for_edge_cases(session):
    assert rubriek_for(session, None, "sales") is None
    assert rubriek_for(session, "NOPE", "purchase") is None
    with pytest.raises(ValueError):
        rubriek_for(session, "NL_21", "bank")
