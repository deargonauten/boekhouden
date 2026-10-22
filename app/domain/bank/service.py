"""Bank statement import: start (preview), confirm, duplicate classification and listings.

Every function flushes and never commits; the caller owns the transaction (same
convention as the documents service). Nothing is booked in the ledger here.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.bank.accounts import BankAccountNotFoundError, get_bank_account
from app.domain.bank.amounts import parse_amount
from app.domain.bank.dedupe import compute_keys
from app.domain.bank.iban import normalize_iban
from app.domain.bank.parsers import BANK_LABELS, FORMAT_LABELS, parse_statement
from app.domain.bank.storage import BANK_STORAGE_FAILED_MESSAGE, BankFileStorage, storage_ext
from app.domain.bank.types import (
    ALREADY_IMPORTED,
    PARSE_ERROR,
    WRONG_ACCOUNT,
    BankImportError,
    ImportPreview,
    ImportResult,
    ParsedStatement,
    PreviewRow,
)
from app.domain.documents.validation import sanitize_filename
from app.domain.errors import DocumentStorageFailedError, LedgerError
from app.domain.ledger import Page
from app.domain.money import format_euro
from app.models import BankAccount, BankImportBatch, BankTransaction

__all__ = [
    "BankAccountNotFoundError",
    "BankStats",
    "BatchRow",
    "ImportBatchNotFoundError",
    "TransactionRow",
    "bank_stats",
    "batch_file_path",
    "classify",
    "confirm_import",
    "get_batch",
    "list_batches",
    "list_transactions",
    "preview_batch",
    "start_import",
]

NO_ACCOUNT_IBAN_WARNING = (
    "In dit bestand staat geen rekeningnummer; controleer of dit de juiste bankrekening is."
)
ALREADY_PROCESSED_MESSAGE = "Deze import is al verwerkt."
INACTIVE_MESSAGE = (
    "Deze bankrekening is niet meer in gebruik, dus je kunt er geen afschriften meer voor importeren. "
    "Kies een andere bankrekening."
)
FILE_MISSING_MESSAGE = (
    "Het opgeslagen bankbestand is niet meer te vinden in data/bank. "
    "Upload het afschrift opnieuw."
)
EXPIRED_MESSAGE = "Dit bestand is al verwerkt. Upload het afschrift opnieuw als je het nogmaals wilt bekijken."
_CHUNK = 500


class ImportBatchNotFoundError(LedgerError):
    code = "IMPORT_BATCH_NOT_FOUND"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- rows for listings --------------------------------------------------------


@dataclass(frozen=True)
class TransactionRow:
    id: int
    booking_date: date
    value_date: date | None
    counterparty_name: str | None
    counterparty_iban: str | None
    description: str
    amount_cents: int  # signed: positive = bij, negative = af
    balance_after_cents: int | None
    bank_account_id: int
    bank_account_name: str
    import_batch_id: int
    status: str


@dataclass(frozen=True)
class BatchRow:
    id: int
    confirmed_at: datetime | None
    bank_account_id: int
    bank_account_name: str
    original_filename: str
    sha256: str
    ext: str
    format_label: str  # e.g. "MT940-bestand"
    bank_label: str | None  # e.g. "ING"
    period_start: date | None
    period_end: date | None
    new_count: int
    skipped_count: int
    maybe_duplicate_count: int


@dataclass(frozen=True)
class BankStats:
    account_count: int  # active bankrekeningen
    transaction_count: int
    last_imported_at: datetime | None


# --- batches and files --------------------------------------------------------


def get_batch(session: Session, batch_id: int) -> BankImportBatch:
    batch = session.get(BankImportBatch, batch_id)
    if batch is None:
        raise ImportBatchNotFoundError(
            "Deze import bestaat niet. Ga terug naar Bank en start een nieuwe import."
        )
    return batch


def batch_file_path(storage: BankFileStorage, batch: BankImportBatch) -> Path:
    """Path of the original file of a batch (read-only, content-addressed)."""
    return storage.path_for(batch.sha256, batch.ext)


def _read_original(storage: BankFileStorage, batch: BankImportBatch) -> bytes:
    try:
        with storage.open(batch.sha256, batch.ext) as fh:
            return fh.read()
    except FileNotFoundError as exc:
        raise BankImportError(PARSE_ERROR, FILE_MISSING_MESSAGE) from exc


def _earliest_confirmation(session: Session, bank_account_id: int, sha256: str) -> datetime | None:
    return session.scalar(
        select(func.min(BankImportBatch.confirmed_at)).where(
            BankImportBatch.bank_account_id == bank_account_id,
            BankImportBatch.sha256 == sha256,
            BankImportBatch.status == "afgerond",
        )
    )


def _check_account_iban(statement: ParsedStatement, account: BankAccount) -> None:
    file_iban = normalize_iban(statement.account_iban)
    if file_iban and file_iban != account.iban:
        raise BankImportError(
            WRONG_ACCOUNT,
            f"Dit afschrift hoort bij {file_iban}, maar je koos {account.name} ({account.iban}). "
            "Kies de juiste bankrekening.",
        )


def _warnings(statement: ParsedStatement) -> tuple[str, ...]:
    warnings = []
    if not statement.account_iban:
        warnings.append(NO_ACCOUNT_IBAN_WARNING)
    diff = statement.balance_difference_cents
    if diff:
        warnings.append(
            f"De saldi in het bestand kloppen niet met de transacties: verschil "
            f"{format_euro(abs(diff))}. Controleer of het bestand compleet is."
        )
    return tuple(warnings)


# --- classification -----------------------------------------------------------


def classify(
    session: Session,
    bank_account_id: int,
    parsed: ParsedStatement,
    *,
    batch_id: int = 0,
    original_filename: str = "",
    sha256: str = "",
    already_imported_on: datetime | None = None,
    warnings: tuple[str, ...] = (),
) -> ImportPreview:
    """Sort every parsed transaction into nieuw / al eerder geïmporteerd / mogelijk dubbel.

    exact: a stored row has the same (dedupe_key, occurrence).
    mogelijk dubbel: no exact match, but a stored row (not otherwise matched) has the same
    booking date, amount and counterparty IBAN (or both empty) with another description.
    """
    transactions = parsed.transactions
    keyed = compute_keys(bank_account_id, parsed)

    stored: dict[tuple[str, int], int] = {}
    wanted = sorted({key for key, _ in keyed})
    for i in range(0, len(wanted), _CHUNK):
        chunk = wanted[i : i + _CHUNK]
        for row_id, key, occ in session.execute(
            select(
                BankTransaction.id, BankTransaction.dedupe_key, BankTransaction.occurrence
            ).where(
                BankTransaction.bank_account_id == bank_account_id,
                BankTransaction.dedupe_key.in_(chunk),
            )
        ):
            stored[(key, occ)] = row_id

    exact = {i: stored.get(k) for i, k in enumerate(keyed)}
    matched_ids = {rid for rid in exact.values() if rid is not None}

    candidates: dict[tuple[date, int, str], list[tuple[int, str]]] = {}
    if transactions:
        first = min(t.booking_date for t in transactions)
        last = max(t.booking_date for t in transactions)
        for row_id, day, amount, iban, key in session.execute(
            select(
                BankTransaction.id,
                BankTransaction.booking_date,
                BankTransaction.amount_cents,
                BankTransaction.counterparty_iban,
                BankTransaction.dedupe_key,
            ).where(
                BankTransaction.bank_account_id == bank_account_id,
                BankTransaction.booking_date.between(first, last),
            )
        ):
            if row_id not in matched_ids:
                candidates.setdefault((day, amount, normalize_iban(iban)), []).append((row_id, key))

    new_rows, existing_rows, maybe_rows = [], [], []
    for index, (tx, (key, occurrence)) in enumerate(zip(transactions, keyed)):
        matched = exact[index]
        if matched is not None:
            existing_rows.append(PreviewRow(index, tx, key, occurrence, matched))
            continue
        pool = candidates.get((tx.booking_date, tx.amount_cents, normalize_iban(tx.counterparty_iban)), [])
        fuzzy = next((c for c in pool if c[1] != key), None)
        if fuzzy is not None:
            pool.remove(fuzzy)  # a stored row explains at most one file row
            maybe_rows.append(PreviewRow(index, tx, key, occurrence, fuzzy[0]))
        else:
            new_rows.append(PreviewRow(index, tx, key, occurrence))

    dates = [t.booking_date for t in transactions]
    return ImportPreview(
        batch_id=batch_id,
        bank_account_id=bank_account_id,
        original_filename=original_filename,
        sha256=sha256,
        format_label=FORMAT_LABELS[parsed.format],
        bank_label=BANK_LABELS.get(parsed.bank or ""),
        period_start=min(dates) if dates else None,
        period_end=max(dates) if dates else None,
        new_rows=tuple(new_rows),
        existing_rows=tuple(existing_rows),
        maybe_rows=tuple(maybe_rows),
        warnings=warnings,
        already_imported_on=already_imported_on,
    )


def _preview_for(
    session: Session, batch: BankImportBatch, statement: ParsedStatement
) -> ImportPreview:
    return classify(
        session,
        batch.bank_account_id,
        statement,
        batch_id=batch.id,
        original_filename=batch.original_filename,
        sha256=batch.sha256,
        already_imported_on=_earliest_confirmation(session, batch.bank_account_id, batch.sha256),
        warnings=_warnings(statement),
    )


# --- import flow --------------------------------------------------------------


def _active_account(session: Session, bank_account_id: int) -> BankAccount:
    account = get_bank_account(session, bank_account_id)
    if not account.is_active:
        raise BankImportError("INACTIVE_ACCOUNT", INACTIVE_MESSAGE)
    return account


def start_import(
    session: Session,
    storage: BankFileStorage,
    bank_account_id: int,
    filename: str | None,
    content: bytes,
) -> ImportPreview:
    """Step 1: parse + check the file, store the original, create a `voorbeeld` batch, classify.

    Inserts no transactions. Raises BankImportError (plain Dutch) when the file cannot be used.
    """
    account = _active_account(session, bank_account_id)
    statement = parse_statement(content, account.bank)
    _check_account_iban(statement, account)

    ext = storage_ext(statement.format, filename or "")
    try:
        stored = storage.write(content, ext)
    except DocumentStorageFailedError as exc:
        raise BankImportError("STORAGE_FAILED", BANK_STORAGE_FAILED_MESSAGE) from exc

    batch = BankImportBatch(
        bank_account_id=account.id,
        status="voorbeeld",
        original_filename=sanitize_filename(filename, ext),
        sha256=stored.sha256,
        ext=stored.ext,
        size=stored.size,
        detected_format=statement.format,
        detected_bank=statement.bank,
        created_at=_now(),
    )
    session.add(batch)
    session.flush()
    return _preview_for(session, batch, statement)


def preview_batch(session: Session, storage: BankFileStorage, batch_id: int) -> ImportPreview:
    """The preview of an existing batch, rebuilt from the stored original (never from stale data)."""
    batch = get_batch(session, batch_id)
    account = get_bank_account(session, batch.bank_account_id)
    statement = parse_statement(_read_original(storage, batch), account.bank)
    return _preview_for(session, batch, statement)


def _make_transaction(
    batch: BankImportBatch, row: PreviewRow, now: datetime
) -> BankTransaction:
    tx = row.transaction
    return BankTransaction(
        bank_account_id=batch.bank_account_id,
        import_batch_id=batch.id,
        booking_date=tx.booking_date,
        value_date=tx.value_date,
        amount_cents=tx.amount_cents,
        currency=tx.currency,
        counterparty_name=tx.counterparty_name,
        counterparty_iban=tx.counterparty_iban,
        description=tx.description,
        end_to_end_id=tx.end_to_end_id,
        bank_reference=tx.bank_reference,
        balance_after_cents=tx.balance_after_cents,
        dedupe_key=row.dedupe_key,
        occurrence=row.occurrence,
        raw=tx.raw,
        status="nieuw",
        created_at=now,
    )


def confirm_import(
    session: Session,
    storage: BankFileStorage,
    batch_id: int,
    include_maybe_ids: set[int],
) -> ImportResult:
    """Step 2: re-read and re-classify the stored file, insert nieuw + opted-in mogelijk dubbel.

    `include_maybe_ids` holds PreviewRow.index values; ids that are not (still) a
    "mogelijk dubbel" row are ignored, so a forged opt-in cannot duplicate an exact match.
    Idempotent: an `afgerond` batch returns its stored counts with `already_processed=True`.
    """
    batch = get_batch(session, batch_id)
    if batch.status == "afgerond":
        return ImportResult(
            batch.id,
            batch.new_count,
            batch.skipped_count,
            batch.maybe_duplicate_count,
            already_processed=True,
        )

    account = _active_account(session, batch.bank_account_id)
    statement = parse_statement(_read_original(storage, batch), account.bank)
    _check_account_iban(statement, account)

    done_on = _earliest_confirmation(session, account.id, batch.sha256)
    if done_on is not None:
        raise BankImportError(
            ALREADY_IMPORTED,
            f"Dit bestand heb je al geïmporteerd op {done_on:%d-%m-%Y}. Er is niets nieuws.",
        )

    preview = classify(
        session,
        account.id,
        statement,
        batch_id=batch.id,
        original_filename=batch.original_filename,
        sha256=batch.sha256,
    )
    chosen = [r for r in preview.maybe_rows if r.index in include_maybe_ids]
    to_insert = sorted([*preview.new_rows, *chosen], key=lambda r: r.index)
    now = _now()

    try:
        with session.begin_nested():
            for row in to_insert:
                session.add(_make_transaction(batch, row, now))
            session.flush()
            batch.status = "afgerond"
            batch.confirmed_at = now
            batch.period_start = preview.period_start
            batch.period_end = preview.period_end
            batch.new_count = len(to_insert)
            batch.skipped_count = preview.existing_count
            batch.maybe_duplicate_count = preview.maybe_count - len(chosen)
            session.flush()
    except IntegrityError as exc:
        raise BankImportError(ALREADY_IMPORTED, ALREADY_PROCESSED_MESSAGE) from exc

    return ImportResult(
        batch.id, len(to_insert), preview.existing_count, preview.maybe_count - len(chosen)
    )


# --- listings -----------------------------------------------------------------


def _like(column, text: str):
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.lower(func.coalesce(column, "")).like(f"%{escaped.lower()}%", escape="\\")


def _amount_candidates(q: str) -> set[int]:
    found = set()
    for style in ("nl", "en"):
        try:
            found.add(abs(parse_amount(q, style)))
        except ValueError:
            pass
        except LedgerError:
            pass
    return found - {0}


def list_transactions(
    session: Session,
    q: str | None = None,
    bank_account_id: int | None = None,
    batch_id: int | None = None,
    page: int = 1,
    per_page: int = 50,
) -> Page:
    """Imported transactions, newest booking date first. `q` searches name, description,
    IBAN and amount (bij or af). Items are TransactionRow."""
    stmt = select(BankTransaction, BankAccount.name).join(
        BankAccount, BankAccount.id == BankTransaction.bank_account_id
    )
    if bank_account_id is not None:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if batch_id is not None:
        stmt = stmt.where(BankTransaction.import_batch_id == batch_id)
    term = " ".join((q or "").split())
    if term:
        conditions = [
            _like(BankTransaction.counterparty_name, term),
            _like(BankTransaction.description, term),
            _like(BankTransaction.counterparty_iban, normalize_iban(term) or term),
        ]
        amounts = _amount_candidates(term)
        if amounts:
            conditions.append(func.abs(BankTransaction.amount_cents).in_(amounts))
        stmt = stmt.where(or_(*conditions))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = min(max(1, page), max(1, -(-total // per_page)))
    rows = session.execute(
        stmt.order_by(BankTransaction.booking_date.desc(), BankTransaction.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    items = [
        TransactionRow(
            id=t.id,
            booking_date=t.booking_date,
            value_date=t.value_date,
            counterparty_name=t.counterparty_name,
            counterparty_iban=t.counterparty_iban,
            description=t.description,
            amount_cents=t.amount_cents,
            balance_after_cents=t.balance_after_cents,
            bank_account_id=t.bank_account_id,
            bank_account_name=name,
            import_batch_id=t.import_batch_id,
            status=t.status,
        )
        for t, name in rows
    ]
    return Page(items=items, page=page, per_page=per_page, total=total)


def list_batches(session: Session, page: int = 1, per_page: int = 50) -> Page:
    """Import history: confirmed (`afgerond`) batches, newest first. Items are BatchRow."""
    stmt = (
        select(BankImportBatch, BankAccount.name)
        .join(BankAccount, BankAccount.id == BankImportBatch.bank_account_id)
        .where(BankImportBatch.status == "afgerond")
    )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = min(max(1, page), max(1, -(-total // per_page)))
    rows = session.execute(
        stmt.order_by(BankImportBatch.confirmed_at.desc(), BankImportBatch.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    items = [
        BatchRow(
            id=b.id,
            confirmed_at=b.confirmed_at,
            bank_account_id=b.bank_account_id,
            bank_account_name=name,
            original_filename=b.original_filename,
            sha256=b.sha256,
            ext=b.ext,
            format_label=FORMAT_LABELS[b.detected_format],
            bank_label=BANK_LABELS.get(b.detected_bank or ""),
            period_start=b.period_start,
            period_end=b.period_end,
            new_count=b.new_count,
            skipped_count=b.skipped_count,
            maybe_duplicate_count=b.maybe_duplicate_count,
        )
        for b, name in rows
    ]
    return Page(items=items, page=page, per_page=per_page, total=total)


def bank_stats(session: Session) -> BankStats:
    return BankStats(
        account_count=session.scalar(
            select(func.count()).select_from(BankAccount).where(BankAccount.is_active.is_(True))
        )
        or 0,
        transaction_count=session.scalar(select(func.count()).select_from(BankTransaction)) or 0,
        last_imported_at=session.scalar(
            select(func.max(BankImportBatch.confirmed_at)).where(
                BankImportBatch.status == "afgerond"
            )
        ),
    )
