import pytest

from app.domain.bank.accounts import (
    create_bank_account,
    deactivate,
    ensure_bank_journal,
    list_bank_accounts,
    selectable_accounts,
    suggest_account,
    suggest_name,
    update_bank_account,
)
from app.domain.bank.service import confirm_import, start_import
from app.domain.bank.types import BankImportError
from app.models import Account, BankAccount, Journal
from tests.bank.conftest import ABN_IBAN, ING_IBAN, fixture_bytes


def test_suggest_prefers_1210_then_1220(session, acc):
    assert suggest_account(session).code == "1210"
    create_bank_account(session, "ING", ING_IBAN, acc("1210"), "ing")
    assert suggest_account(session).code == "1220"
    create_bank_account(session, "ABN", ABN_IBAN, acc("1220"), "abn_amro")
    assert suggest_account(session) is None


def test_suggest_name_from_bank():
    assert suggest_name("ing") == "Zakelijke rekening ING"
    assert suggest_name("abn_amro") == "Zakelijke rekening ABN AMRO"
    assert suggest_name(None) == "Zakelijke rekening"


def test_selectable_accounts_are_assets_including_1210(session):
    accounts = selectable_accounts(session)
    codes = {a.code for a in accounts}
    assert "1210" in codes and "1220" in codes
    assert all(a.type == "asset" for a in accounts)


def test_create_normalises_iban_and_reuses_bank_journal(session, acc):
    ba = create_bank_account(session, "  Zakelijk ING ", "nl20 ingb 0001 2345 67", acc("1210"), "ing")
    assert ba.iban == ING_IBAN
    assert ba.name == "Zakelijk ING"
    assert ba.is_active is True
    journal = session.get(Journal, ba.journal_id)
    assert journal.code == "BANK"
    assert journal.account_id == acc("1210")


def test_create_makes_new_journal_when_none_for_account(session, acc):
    ba = create_bank_account(session, "Spaar", ABN_IBAN, acc("1220"), "abn_amro")
    journal = session.get(Journal, ba.journal_id)
    assert journal.code == "BANK2"
    assert journal.type == "bank"
    assert journal.account_id == acc("1220")
    assert journal.name == "Spaar"


def test_ensure_bank_journal_increments_codes_and_is_idempotent(session, acc):
    a1220 = session.get(Account, acc("1220"))
    j1 = ensure_bank_journal(session, a1220, "Eerste")
    assert ensure_bank_journal(session, a1220, "Tweede").id == j1.id
    other = Account(code="1235", name="Extra bank", type="asset", is_postable=True, is_active=True)
    session.add(other)
    session.flush()
    assert ensure_bank_journal(session, other, "Extra").code == "BANK3"


def test_invalid_iban_gives_plain_message(session, acc):
    with pytest.raises(BankImportError) as exc:
        create_bank_account(session, "X", "NL00INGB0001234567", acc("1210"), "ing")
    assert exc.value.code == "BAD_IBAN"
    assert "Dit IBAN-nummer klopt niet" in exc.value.message
    assert "NL91 ABNA 0417 1643 00" in exc.value.message


def test_duplicate_iban_refused(session, acc):
    create_bank_account(session, "A", ING_IBAN, acc("1210"), "ing")
    with pytest.raises(BankImportError) as exc:
        create_bank_account(session, "B", ING_IBAN.lower(), acc("1220"), "ing")
    assert "al in gebruik" in exc.value.message


def test_one_bankrekening_per_grootboekrekening(session, acc):
    create_bank_account(session, "Zakelijk ING", ING_IBAN, acc("1210"), "ing")
    with pytest.raises(BankImportError) as exc:
        create_bank_account(session, "Andere", ABN_IBAN, acc("1210"), "abn_amro")
    assert exc.value.code == "ACCOUNT_IN_USE"
    assert exc.value.message.startswith("Deze grootboekrekening hoort al bij Zakelijk ING.")


@pytest.mark.parametrize("code", ["8000", "4200"])
def test_account_must_be_asset(session, acc, code):
    with pytest.raises(BankImportError):
        create_bank_account(session, "X", ING_IBAN, acc(code), "ing")


def test_account_must_be_active_and_postable(session, acc):
    a = session.get(Account, acc("1220"))
    a.is_active = False
    session.flush()
    with pytest.raises(BankImportError):
        create_bank_account(session, "X", ING_IBAN, a.id, "ing")
    a.is_active = True
    a.is_postable = False
    session.flush()
    with pytest.raises(BankImportError):
        create_bank_account(session, "X", ING_IBAN, a.id, "ing")


def test_name_required_and_bank_validated(session, acc):
    with pytest.raises(BankImportError):
        create_bank_account(session, "  ", ING_IBAN, acc("1210"), "ing")
    with pytest.raises(BankImportError):
        create_bank_account(session, "X", ING_IBAN, acc("1210"), "nepbank")


def test_rename_and_deactivate_never_delete(session, ing_account):
    update_bank_account(session, ing_account.id, name="Hoofdrekening", bank="ing")
    assert session.get(BankAccount, ing_account.id).name == "Hoofdrekening"
    deactivate(session, ing_account.id)
    assert session.get(BankAccount, ing_account.id).is_active is False
    assert list_bank_accounts(session) != []
    assert list_bank_accounts(session, active_only=True) == []


def test_iban_and_account_editable_without_imports(session, ing_account, acc):
    update_bank_account(
        session, ing_account.id, name="N", bank="ing", iban=ABN_IBAN, account_id=acc("1220")
    )
    ba = session.get(BankAccount, ing_account.id)
    assert ba.iban == ABN_IBAN and ba.account_id == acc("1220")
    assert session.get(Journal, ba.journal_id).account_id == acc("1220")


def test_iban_and_account_locked_after_import(session, ing_account, bank_storage, acc):
    preview = start_import(session, bank_storage, ing_account.id, "a.csv", fixture_bytes("ing.csv"))
    confirm_import(session, bank_storage, preview.batch_id, set())
    with pytest.raises(BankImportError) as exc:
        update_bank_account(session, ing_account.id, name="N", bank="ing", iban=ABN_IBAN)
    assert exc.value.code == "ACCOUNT_IN_USE"
    with pytest.raises(BankImportError):
        update_bank_account(session, ing_account.id, name="N", bank="ing", account_id=acc("1220"))
    update_bank_account(
        session, ing_account.id, name="Nieuw", bank="overig", iban=ING_IBAN, account_id=acc("1210")
    )
    assert session.get(BankAccount, ing_account.id).name == "Nieuw"


def test_list_orders_by_name(session, ing_account, abn_account):
    names = [b.name for b in list_bank_accounts(session)]
    assert names == sorted(names, key=str.casefold)
