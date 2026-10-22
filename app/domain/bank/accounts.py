"""Bankrekeningen: the owner's bank accounts, each linked to a grootboekrekening and a bank dagboek.

All functions flush, never commit; the caller owns the transaction.
"""

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.bank.iban import is_valid_iban, normalize_iban
from app.domain.bank.types import ACCOUNT_IN_USE, BAD_IBAN, BANKS, BankImportError
from app.domain.errors import LedgerError
from app.models import Account, BankAccount, BankImportBatch, Journal

BANK_NAMES = {
    "ing": "ING",
    "rabobank": "Rabobank",
    "abn_amro": "ABN AMRO",
    "bunq": "bunq",
    "overig": "",
}

BAD_IBAN_MESSAGE = (
    "Dit IBAN-nummer klopt niet. Controleer of je alle tekens hebt overgenomen "
    "(bijvoorbeeld NL91 ABNA 0417 1643 00)."
)
NAME_REQUIRED_MESSAGE = "Geef de bankrekening een naam, bijvoorbeeld 'Zakelijke rekening ING'."
DUPLICATE_IBAN_MESSAGE = (
    "Dit IBAN-nummer is al in gebruik voor de bankrekening {name}. "
    "Gebruik die bankrekening of controleer het nummer."
)
BAD_ACCOUNT_MESSAGE = (
    "Kies als grootboekrekening een actieve rekening van het type bezittingen (zoals 1210 Bank)."
)
LOCKED_MESSAGE = (
    "Er zijn al afschriften geïmporteerd voor deze bankrekening. Het IBAN-nummer en de "
    "grootboekrekening kun je daarom niet meer wijzigen; de naam wel."
)
BAD_BANK_MESSAGE = "Kies een bank uit de lijst, of 'overige bank'."


class BankAccountNotFoundError(LedgerError):
    code = "BANK_ACCOUNT_NOT_FOUND"


def suggest_name(bank: str | None) -> str:
    label = BANK_NAMES.get(bank or "", "")
    return f"Zakelijke rekening {label}".strip()


def suggest_account(session: Session) -> Account | None:
    """First active asset account among 1210, then 1220, not yet linked to a bankrekening."""
    taken = select(BankAccount.account_id)
    for code in ("1210", "1220"):
        account = session.scalar(
            select(Account).where(
                Account.code == code,
                Account.type == "asset",
                Account.is_active.is_(True),
                Account.is_postable.is_(True),
                Account.id.not_in(taken),
            )
        )
        if account is not None:
            return account
    return None


def selectable_accounts(session: Session) -> list[Account]:
    """Asset accounts a bankrekening may be linked to (the bank-selectable ones plus 1210 Bank)."""
    stmt = (
        select(Account)
        .where(
            Account.type == "asset",
            Account.is_active.is_(True),
            Account.is_postable.is_(True),
            or_(Account.selectable_bank.is_(True), Account.code == "1210"),
        )
        .order_by(Account.code)
    )
    return list(session.scalars(stmt))


def get_bank_account(session: Session, bank_account_id: int) -> BankAccount:
    account = session.get(BankAccount, bank_account_id)
    if account is None:
        raise BankAccountNotFoundError(
            "Deze bankrekening bestaat niet. Ga terug naar Bank en kies een bankrekening uit de lijst."
        )
    return account


def list_bank_accounts(session: Session, *, active_only: bool = False) -> list[BankAccount]:
    stmt = select(BankAccount)
    if active_only:
        stmt = stmt.where(BankAccount.is_active.is_(True))
    return sorted(session.scalars(stmt), key=lambda b: (b.name.casefold(), b.id))


def has_imports(session: Session, bank_account_id: int) -> bool:
    """True once a statement was confirmed for this bankrekening (IBAN/account then locked)."""
    return bool(
        session.scalar(
            select(
                exists().where(
                    BankImportBatch.bank_account_id == bank_account_id,
                    BankImportBatch.status == "afgerond",
                )
            )
        )
    )


def ensure_bank_journal(session: Session, account: Account, name: str) -> Journal:
    """Reuse the active bank dagboek of this grootboekrekening, else create BANK, BANK2, ..."""
    journal = session.scalar(
        select(Journal)
        .where(
            Journal.type == "bank", Journal.account_id == account.id, Journal.is_active.is_(True)
        )
        .order_by(Journal.id)
    )
    if journal is not None:
        return journal
    taken = set(session.scalars(select(Journal.code)))
    n = 1
    while (code := "BANK" if n == 1 else f"BANK{n}") in taken:
        n += 1
    journal = Journal(code=code, name=name, type="bank", account_id=account.id, is_active=True)
    session.add(journal)
    session.flush()
    return journal


def _clean_name(name: str | None) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise BankImportError("NAME_REQUIRED", NAME_REQUIRED_MESSAGE)
    return cleaned


def _clean_bank(bank: str | None) -> str | None:
    if not bank:
        return None
    if bank not in BANKS:
        raise BankImportError("BAD_BANK", BAD_BANK_MESSAGE)
    return bank


def _clean_iban(session: Session, iban: str | None, *, own_id: int | None = None) -> str:
    normalised = normalize_iban(iban)
    if not is_valid_iban(normalised):
        raise BankImportError(BAD_IBAN, BAD_IBAN_MESSAGE)
    other = session.scalar(select(BankAccount).where(BankAccount.iban == normalised))
    if other is not None and other.id != own_id:
        raise BankImportError(
            "DUPLICATE_IBAN", DUPLICATE_IBAN_MESSAGE.format(name=other.name)
        )
    return normalised


def _check_account(session: Session, account_id: int, *, own_id: int | None = None) -> Account:
    account = session.get(Account, account_id)
    if (
        account is None
        or account.type != "asset"
        or not account.is_active
        or not account.is_postable
    ):
        raise BankImportError("BAD_ACCOUNT", BAD_ACCOUNT_MESSAGE)
    other = session.scalar(select(BankAccount).where(BankAccount.account_id == account_id))
    if other is not None and other.id != own_id:
        raise BankImportError(
            ACCOUNT_IN_USE,
            f"Deze grootboekrekening hoort al bij {other.name}. "
            "Kies een andere rekening of gebruik die bankrekening.",
        )
    return account


def create_bank_account(
    session: Session, name: str, iban: str, account_id: int, bank: str | None = None
) -> BankAccount:
    name = _clean_name(name)
    bank = _clean_bank(bank)
    normalised = _clean_iban(session, iban)
    account = _check_account(session, account_id)
    journal = ensure_bank_journal(session, account, name)
    bank_account = BankAccount(
        name=name,
        iban=normalised,
        bank=bank,
        account_id=account.id,
        journal_id=journal.id,
        is_active=True,
    )
    session.add(bank_account)
    try:
        session.flush()
    except IntegrityError as exc:  # concurrent insert of the same IBAN / grootboekrekening
        raise BankImportError(
            "DUPLICATE_IBAN",
            "Deze bankrekening bestaat al (zelfde IBAN-nummer of grootboekrekening). "
            "Ververs de pagina en controleer de lijst.",
        ) from exc
    return bank_account


def update_bank_account(
    session: Session,
    bank_account_id: int,
    *,
    name: str,
    bank: str | None,
    iban: str | None = None,
    account_id: int | None = None,
) -> BankAccount:
    """Rename / change bank; IBAN and grootboekrekening only while nothing was imported.

    `iban` / `account_id` of None (or equal to the current value) mean unchanged.
    """
    bank_account = get_bank_account(session, bank_account_id)
    new_name = _clean_name(name)
    new_bank = _clean_bank(bank)

    new_iban = bank_account.iban
    if iban is not None and normalize_iban(iban) != bank_account.iban:
        if has_imports(session, bank_account.id):
            raise BankImportError(ACCOUNT_IN_USE, LOCKED_MESSAGE)
        new_iban = _clean_iban(session, iban, own_id=bank_account.id)

    new_account = None
    if account_id is not None and account_id != bank_account.account_id:
        if has_imports(session, bank_account.id):
            raise BankImportError(ACCOUNT_IN_USE, LOCKED_MESSAGE)
        new_account = _check_account(session, account_id, own_id=bank_account.id)

    bank_account.name = new_name
    bank_account.bank = new_bank
    bank_account.iban = new_iban
    if new_account is not None:
        bank_account.account_id = new_account.id
        bank_account.journal_id = ensure_bank_journal(session, new_account, new_name).id
    session.flush()
    return bank_account


def deactivate(session: Session, bank_account_id: int) -> BankAccount:
    """Bankrekeningen are never deleted; an inactive one accepts no new imports."""
    bank_account = get_bank_account(session, bank_account_id)
    bank_account.is_active = False
    session.flush()
    return bank_account
