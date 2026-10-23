import pytest
from sqlalchemy import select

from app.domain.errors import LedgerError
from app.domain.ledger import (
    add_account, list_accounts_for, set_account_active, set_account_contexts,
    set_account_vat_default, suggest_vat_code,
)
from app.models import Account, VatCode


def codes(session, ctx):
    return [a.code for a in list_accounts_for(session, ctx)]


def test_list_accounts_for_per_context(session):
    purchase = codes(session, "purchase")
    assert "4635" in purchase and "0110" in purchase
    assert "8400" not in purchase and "1210" not in purchase and "1300" not in purchase
    assert purchase == sorted(purchase)
    assert "8400" in codes(session, "sales") and "4635" not in codes(session, "sales")
    assert "2010" in codes(session, "bank") and "1210" not in codes(session, "bank")


def test_list_accounts_for_excludes_inactive_and_kopregel(session):
    a = add_account(session, code="4971", name="Eigen", type="expense")
    assert "4971" in codes(session, "purchase")
    set_account_active(session, a.id, False)
    assert "4971" not in codes(session, "purchase")
    h = add_account(session, code="4972", name="Kop", type="expense", is_postable=False)
    assert "4972" not in codes(session, "purchase") and h.selectable_purchase


def test_list_accounts_for_unknown_context(session):
    with pytest.raises(ValueError):
        list_accounts_for(session, "kas")


@pytest.mark.parametrize(
    "type_,expected",
    [("expense", (True, False, True)), ("revenue", (False, True, True)),
     ("asset", (False, False, True)), ("liability", (False, False, True)),
     ("equity", (False, False, True))],
)
def test_add_account_default_flags(session, type_, expected):
    a = add_account(session, code="4973", name="X", type=type_)
    assert (a.selectable_purchase, a.selectable_sales, a.selectable_bank) == expected


def test_add_account_explicit_flags(session):
    a = add_account(session, code="4973", name="X", type="expense",
                    selectable_purchase=False, selectable_sales=True)
    assert (a.selectable_purchase, a.selectable_sales, a.selectable_bank) == (False, True, True)


def test_suggest_vat_code(session, acc):
    assert suggest_vat_code(session, acc("4635")) == "NL_21"
    assert suggest_vat_code(session, acc("4835")) == "GEEN"
    assert suggest_vat_code(session, 999999) is None
    session.get(VatCode, "NL_21").is_active = False
    session.flush()
    assert suggest_vat_code(session, acc("4635")) is None


def test_set_account_vat_default(session, acc):
    set_account_vat_default(session, acc("4635"), "NL_9")
    assert session.get(Account, acc("4635")).default_vat_code == "NL_9"
    set_account_vat_default(session, acc("4635"), None)
    assert session.get(Account, acc("4635")).default_vat_code is None
    # system account allowed
    set_account_vat_default(session, acc("8400"), "NL_21")


def test_set_account_vat_default_errors(session, acc):
    with pytest.raises(LedgerError) as e:
        set_account_vat_default(session, acc("4635"), "NOPE")
    assert e.value.code == "INVALID_VAT_CODE"
    session.get(VatCode, "NL_9").is_active = False
    session.flush()
    with pytest.raises(LedgerError) as e:
        set_account_vat_default(session, acc("4635"), "NL_9")
    assert e.value.code == "INVALID_VAT_CODE"
    h = add_account(session, code="4974", name="Kop", type="expense", is_postable=False)
    with pytest.raises(LedgerError) as e:
        set_account_vat_default(session, h.id, "NL_21")
    assert e.value.message == "Een kopregel heeft geen btw-tarief; kies een rekening eronder."


def test_set_account_contexts(session, acc):
    a = set_account_contexts(session, acc("4635"), purchase=False, sales=True, bank=False)
    assert (a.selectable_purchase, a.selectable_sales, a.selectable_bank) == (False, True, False)
    assert "4635" in codes(session, "sales") and "4635" not in codes(session, "purchase")
    # 8000 is system but allowed
    set_account_contexts(session, acc("8400"), purchase=True, sales=True, bank=True)


@pytest.mark.parametrize("code", ["1210", "1300", "4950", "2000"])
def test_set_account_contexts_refused_on_hidden_system(session, acc, code):
    with pytest.raises(LedgerError) as e:
        set_account_contexts(session, acc(code), purchase=True, sales=False, bank=False)
    assert e.value.message == (
        "Dit is een standaardrekening die het programma zelf gebruikt; hij verschijnt niet in "
        "keuzelijsten en dat kun je niet aanpassen."
    )


def test_set_account_contexts_unknown_account(session):
    with pytest.raises(LedgerError) as e:
        set_account_contexts(session, 999999, purchase=True, sales=True, bank=True)
    assert e.value.code == "ACCOUNT_NOT_FOUND"
