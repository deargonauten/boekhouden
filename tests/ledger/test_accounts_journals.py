from datetime import date

import pytest

from app.domain.errors import LedgerError
from app.domain.ledger import (
    NewEntry, NewLine, add_account, add_journal, delete_account, list_accounts,
    list_journals, post_entry, rename_account, set_account_active, set_journal_active,
)


def by_code(session, code):
    return [a for a in list_accounts(session) if a.code == code][0]


def test_add_account(session):
    a = add_account(session, code="4250", name="Boeken", type="expense")
    assert a.id and a.is_active and not a.is_system and a.is_postable
    assert "4250" in [x.code for x in list_accounts(session)]


@pytest.mark.parametrize("code", ["425", "42500", "abcd", "42a0", ""])
def test_add_account_bad_code(session, code):
    with pytest.raises(LedgerError) as ei:
        add_account(session, code=code, name="X", type="expense")
    assert ei.value.code == "INVALID_ACCOUNT"


def test_add_account_validation(session):
    cases = [
        (dict(code="1210", name="X", type="asset"), "DUPLICATE_CODE"),
        (dict(code="4251", name="X", type="bogus"), "INVALID_ACCOUNT"),
        (dict(code="4251", name="  ", type="expense"), "INVALID_ACCOUNT"),
        (dict(code="4251", name="X", type="expense", default_vat_code="NOPE"), "INVALID_VAT_CODE"),
    ]
    for kw, code in cases:
        with pytest.raises(LedgerError) as ei:
            add_account(session, **kw)
        assert ei.value.code == code, kw


def test_deactivate_reactivate(session, acc):
    set_account_active(session, acc("4200"), False)
    assert by_code(session, "4200").is_active is False
    set_account_active(session, acc("4200"), True)
    assert by_code(session, "4200").is_active is True
    with pytest.raises(LedgerError) as ei:
        set_account_active(session, 99999, False)
    assert ei.value.code == "ACCOUNT_NOT_FOUND"


def test_rename_rules(session, acc):
    assert rename_account(session, acc("4200"), "Kantoor").name == "Kantoor"
    with pytest.raises(LedgerError) as ei:
        rename_account(session, acc("1210"), "Anders")  # system account
    assert ei.value.code == "SYSTEM_ACCOUNT"


def test_delete_rules(session, acc, jrn, year2025):
    a = add_account(session, code="4251", name="Tmp", type="expense")
    delete_account(session, a.id)
    assert "4251" not in [x.code for x in list_accounts(session)]
    with pytest.raises(LedgerError) as ei:
        delete_account(session, acc("1300"))
    assert ei.value.code == "SYSTEM_ACCOUNT"
    b = add_account(session, code="4252", name="Used", type="asset")
    post_entry(session, NewEntry(jrn("MEM"), date(2025, 3, 1), "x", [
        NewLine(b.id, debit_cents=5), NewLine(acc("1210"), credit_cents=5)]))
    with pytest.raises(LedgerError) as ei:
        delete_account(session, b.id)
    assert ei.value.code == "ACCOUNT_IN_USE"


def test_add_and_deactivate_journal(session, acc):
    j = add_journal(session, code="BANK2", name="Zakelijk spaar", type="bank", account_id=acc("1210"))
    assert j.is_active
    assert "BANK2" in [x.code for x in list_journals(session)]
    set_journal_active(session, j.id, False)
    assert [x for x in list_journals(session) if x.code == "BANK2"][0].is_active is False


def test_add_journal_validation(session, acc):
    cases = [
        dict(code="bank9", name="x", type="bank", account_id=acc("1210")),  # lowercase
        dict(code="TOOLONG1", name="x", type="memoriaal"),
        dict(code="B3", name="x", type="bank"),  # no account
        dict(code="B3", name="x", type="bank", account_id=acc("8000")),  # not an asset
        dict(code="B3", name="x", type="wat"),
    ]
    for kw in cases:
        with pytest.raises(LedgerError) as ei:
            add_journal(session, **kw)
        assert ei.value.code == "INVALID_JOURNAL", kw
    with pytest.raises(LedgerError) as ei:
        add_journal(session, code="VK", name="dup", type="verkoop")
    assert ei.value.code == "DUPLICATE_CODE"


def test_journal_account_inactive_rejected(session, acc):
    set_account_active(session, acc("1100"), False)
    with pytest.raises(LedgerError) as ei:
        add_journal(session, code="KAS2", name="x", type="kas", account_id=acc("1100"))
    assert ei.value.code == "INVALID_JOURNAL"
