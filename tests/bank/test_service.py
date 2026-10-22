import os
import stat
from datetime import date

import pytest
from sqlalchemy import func, select

from app.domain.bank import service
from app.domain.bank.accounts import deactivate
from app.domain.bank.service import (
    BankAccountNotFoundError,
    ImportBatchNotFoundError,
    bank_stats,
    batch_file_path,
    confirm_import,
    get_batch,
    list_batches,
    list_transactions,
    preview_batch,
    start_import,
)
from app.domain.bank.types import BankImportError
from app.domain.errors import DocumentStorageFailedError
from app.models import BankImportBatch, BankTransaction
from tests.bank.conftest import fixture_bytes

MT940 = "mt940_ing.sta"
ING_CSV = "ing.csv"


def count_tx(session):
    return session.scalar(select(func.count()).select_from(BankTransaction))


def import_file(session, storage, account, name, include=frozenset()):
    preview = start_import(session, storage, account.id, name, fixture_bytes(name))
    result = confirm_import(session, storage, preview.batch_id, set(include))
    session.commit()
    return preview, result


# --- start_import -------------------------------------------------------------


def test_start_import_stores_file_and_creates_preview_batch(session, bank_storage, ing_account):
    content = fixture_bytes(MT940)
    preview = start_import(session, bank_storage, ing_account.id, "../afschrift.sta", content)
    session.commit()

    batch = session.get(BankImportBatch, preview.batch_id)
    assert batch.status == "voorbeeld"
    assert batch.original_filename == "afschrift.sta"
    assert batch.detected_format == "mt940"
    assert batch.detected_bank == "ing"
    assert batch.size == len(content)
    assert batch.confirmed_at is None
    assert count_tx(session) == 0

    path = bank_storage.path_for(batch.sha256, batch.ext)
    assert path.read_bytes() == content
    assert path.parent.name == batch.sha256[:2]
    assert not os.access(path, os.W_OK) or not (path.stat().st_mode & stat.S_IWUSR)
    assert batch_file_path(bank_storage, batch) == path


def test_preview_content(session, bank_storage, ing_account):
    preview = start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    assert preview.format_label == "MT940-bestand"
    assert preview.bank_label == "ING"
    assert preview.new_count == 5 and preview.existing_count == 0 and preview.maybe_count == 0
    assert preview.period_start == date(2024, 3, 1)
    assert preview.period_end == date(2024, 3, 4)
    assert preview.can_confirm
    assert preview.warnings == ()
    assert [r.index for r in preview.new_rows] == [0, 1, 2, 3, 4]
    # identical coffees: occurrence 1 and 2
    assert [r.occurrence for r in preview.new_rows[2:4]] == [1, 2]


def test_preview_batch_rebuilds_same_preview(session, bank_storage, ing_account):
    first = start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    again = preview_batch(session, bank_storage, first.batch_id)
    assert again == first


def test_wrong_iban_is_refused(session, bank_storage, abn_account):
    with pytest.raises(BankImportError) as exc:
        start_import(session, bank_storage, abn_account.id, "a.sta", fixture_bytes(MT940))
    assert exc.value.code == "WRONG_ACCOUNT"
    assert "NL20INGB0001234567" in exc.value.message
    assert "Zakelijk ABN (NL91ABNA0417164300)" in exc.value.message
    assert "Kies de juiste bankrekening." in exc.value.message
    assert session.scalar(select(func.count()).select_from(BankImportBatch)) == 0


def test_file_without_account_iban_warns(session, bank_storage, ing_account):
    preview = start_import(session, bank_storage, ing_account.id, "a.tab", fixture_bytes("abn_amro.tab"))
    assert "In dit bestand staat geen rekeningnummer" in " ".join(preview.warnings)
    assert preview.can_confirm


def test_inactive_account_is_refused(session, bank_storage, ing_account):
    deactivate(session, ing_account.id)
    with pytest.raises(BankImportError) as exc:
        start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    assert "niet meer in gebruik" in exc.value.message


def test_unknown_account_raises_not_found(session, bank_storage):
    with pytest.raises(BankAccountNotFoundError):
        start_import(session, bank_storage, 999, "a.sta", fixture_bytes(MT940))


def test_unreadable_file_gives_plain_error(session, bank_storage, ing_account):
    with pytest.raises(BankImportError) as exc:
        start_import(session, bank_storage, ing_account.id, "x.pdf", b"%PDF-1.4 hello")
    assert exc.value.code == "UNKNOWN_FORMAT"


def test_storage_failure_becomes_plain_dutch_bank_error(session, bank_storage, ing_account, monkeypatch):
    def boom(content, ext):
        raise DocumentStorageFailedError("raw technical text")

    monkeypatch.setattr(bank_storage, "write", boom)
    with pytest.raises(BankImportError) as exc:
        start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    assert "opgeslagen" in exc.value.message
    assert "raw technical text" not in exc.value.message


def test_balance_mismatch_warns(session, bank_storage, ing_account):
    content = fixture_bytes(MT940).replace(b":62F:C240304EUR2000,90", b":62F:C240304EUR2012,90")
    preview = start_import(session, bank_storage, ing_account.id, "a.sta", content)
    text = " ".join(preview.warnings)
    assert "De saldi in het bestand kloppen niet met de transacties: verschil € 12,00." in text


# --- confirm_import -----------------------------------------------------------


def test_confirm_inserts_transactions_and_finishes_batch(session, bank_storage, ing_account):
    preview, result = import_file(session, bank_storage, ing_account, MT940)
    assert (result.new_count, result.skipped_count, result.maybe_skipped_count) == (5, 0, 0)
    assert result.batch_id == preview.batch_id and not result.already_processed

    batch = session.get(BankImportBatch, preview.batch_id)
    assert batch.status == "afgerond"
    assert batch.confirmed_at is not None
    assert (batch.new_count, batch.skipped_count, batch.maybe_duplicate_count) == (5, 0, 0)
    assert batch.period_start == date(2024, 3, 1) and batch.period_end == date(2024, 3, 4)

    rows = list(session.scalars(select(BankTransaction).order_by(BankTransaction.id)))
    assert [r.amount_cents for r in rows] == [-1210, 100000, -350, -350, 2000]
    assert all(r.status == "nieuw" and r.journal_entry_id is None for r in rows)
    assert all(r.bank_account_id == ing_account.id and r.import_batch_id == batch.id for r in rows)
    assert [r.occurrence for r in rows[2:4]] == [1, 2]
    assert rows[0].counterparty_name == "Kantoor BV"
    assert rows[0].counterparty_iban == "NL02ABNA0123456789"
    assert rows[0].raw


def test_confirm_is_idempotent(session, bank_storage, ing_account):
    preview, _ = import_file(session, bank_storage, ing_account, MT940)
    again = confirm_import(session, bank_storage, preview.batch_id, set())
    assert again.already_processed is True
    assert (again.new_count, again.skipped_count) == (5, 0)
    assert count_tx(session) == 5


def test_same_file_again_is_flagged_and_cannot_be_confirmed(session, bank_storage, ing_account):
    first, _ = import_file(session, bank_storage, ing_account, MT940)
    second = start_import(session, bank_storage, ing_account.id, "again.sta", fixture_bytes(MT940))
    assert second.already_imported_on is not None
    assert second.existing_count == 5 and second.new_count == 0
    assert not second.can_confirm
    with pytest.raises(BankImportError) as exc:
        confirm_import(session, bank_storage, second.batch_id, set())
    assert exc.value.code == "ALREADY_IMPORTED"
    assert count_tx(session) == 5
    assert session.get(BankImportBatch, second.batch_id).status == "voorbeeld"


def test_same_bytes_for_other_account_is_not_flagged(session, bank_storage, ing_account, abn_account):
    import_file(session, bank_storage, abn_account, "camt053_002.xml")
    assert count_tx(session) == 7


def test_overlapping_statement_other_format_gives_maybe_duplicates(session, bank_storage, ing_account):
    import_file(session, bank_storage, ing_account, MT940)
    preview = start_import(session, bank_storage, ing_account.id, "ing.csv", fixture_bytes(ING_CSV))
    assert preview.new_count == 0
    assert preview.existing_count + preview.maybe_count == 4
    assert preview.maybe_count >= 1
    assert not preview.already_imported_on
    # maybe rows point at the stored transaction
    assert all(r.matched_transaction_id for r in preview.maybe_rows)


def test_maybe_rows_are_skipped_by_default(session, bank_storage, ing_account):
    import_file(session, bank_storage, ing_account, MT940)
    preview = start_import(session, bank_storage, ing_account.id, "ing.csv", fixture_bytes(ING_CSV))
    default = confirm_import(session, bank_storage, preview.batch_id, set())
    assert default.new_count == 0
    assert default.maybe_skipped_count == preview.maybe_count
    assert default.skipped_count == preview.existing_count
    assert count_tx(session) == 5


def test_opt_in_imports_maybe_row_and_forged_opt_in_is_ignored(session, bank_storage, ing_account):
    import_file(session, bank_storage, ing_account, MT940)
    csv = fixture_bytes(ING_CSV) + b'"20240305";"Nieuw BV";"NL20INGB0001234567";"";"OV";"Bij";"5,00";"Overschrijving";"Extra"\n'
    preview = start_import(session, bank_storage, ing_account.id, "ing.csv", csv)
    assert preview.new_count == 1 and preview.maybe_count >= 1
    maybe_index = preview.maybe_rows[0].index
    existing_index = preview.existing_rows[0].index

    result = confirm_import(session, bank_storage, preview.batch_id, {maybe_index, existing_index, 999})
    assert result.new_count == 2  # 1 new + 1 opted-in maybe
    assert result.skipped_count == preview.existing_count
    assert result.maybe_skipped_count == preview.maybe_count - 1
    assert count_tx(session) == 7
    # the forged opt-in did not duplicate the exact duplicate
    keys = list(session.execute(select(BankTransaction.dedupe_key, BankTransaction.occurrence)))
    assert len(keys) == len(set(keys))


def test_overlapping_same_format_imports_only_new_rows(session, bank_storage, ing_account):
    import_file(session, bank_storage, ing_account, ING_CSV)
    extra = b'"20240306";"Nieuw BV";"NL20INGB0001234567";"";"OV";"Bij";"5,00";"Overschrijving";"Extra"\n'
    preview = start_import(session, bank_storage, ing_account.id, "o.csv", fixture_bytes(ING_CSV) + extra)
    assert (preview.new_count, preview.existing_count, preview.maybe_count) == (1, 4, 0)
    result = confirm_import(session, bank_storage, preview.batch_id, set())
    session.commit()
    assert (result.new_count, result.skipped_count) == (1, 4)
    assert count_tx(session) == 5


def test_third_identical_payment_in_later_file_is_new(session, bank_storage, ing_account):
    """Two coffees stored; a later file with three identical lines only adds the third."""
    import_file(session, bank_storage, ing_account, ING_CSV)
    coffee = b'"20240304";"Koffiebar";"NL20INGB0001234567";"";"BA";"Af";"3,50";"Betaalautomaat";"Koffie"\n'
    content = fixture_bytes(ING_CSV) + coffee
    preview = start_import(session, bank_storage, ing_account.id, "c.csv", content)
    assert preview.new_count == 1 and preview.new_rows[0].occurrence == 3
    assert preview.maybe_count == 0


def test_concurrent_confirm_hits_unique_key_and_inserts_nothing(session, bank_storage, ing_account, monkeypatch):
    preview = start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    session.commit()
    stale = preview  # classified before the "other" confirm ran
    import_file_other = start_import(session, bank_storage, ing_account.id, "b.sta", fixture_bytes(MT940) + b"\n")
    confirm_import(session, bank_storage, import_file_other.batch_id, set())
    session.commit()
    assert count_tx(session) == 5

    monkeypatch.setattr(service, "classify", lambda *a, **k: stale)
    # the stale classification says "all new" while the rows exist
    with pytest.raises(BankImportError) as exc:
        confirm_import(session, bank_storage, preview.batch_id, set())
    assert exc.value.message == "Deze import is al verwerkt."
    session.rollback()
    assert count_tx(session) == 5
    assert session.get(BankImportBatch, preview.batch_id).status == "voorbeeld"


def test_confirm_failure_leaves_no_partial_rows(session, bank_storage, ing_account, monkeypatch):
    preview = start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    session.commit()
    real = service._make_transaction
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("disk on fire")
        return real(*args)

    monkeypatch.setattr(service, "_make_transaction", flaky)
    with pytest.raises(RuntimeError):
        confirm_import(session, bank_storage, preview.batch_id, set())
    session.rollback()
    assert count_tx(session) == 0
    assert session.get(BankImportBatch, preview.batch_id).status == "voorbeeld"


def test_confirm_unknown_batch(session, bank_storage):
    with pytest.raises(ImportBatchNotFoundError):
        confirm_import(session, bank_storage, 12345, set())
    with pytest.raises(ImportBatchNotFoundError):
        get_batch(session, 12345)


def test_confirm_refused_for_inactive_account(session, bank_storage, ing_account):
    preview = start_import(session, bank_storage, ing_account.id, "a.sta", fixture_bytes(MT940))
    deactivate(session, ing_account.id)
    with pytest.raises(BankImportError):
        confirm_import(session, bank_storage, preview.batch_id, set())


# --- listing ------------------------------------------------------------------


def test_list_transactions_order_filters_and_search(session, bank_storage, ing_account, abn_account):
    p1, _ = import_file(session, bank_storage, ing_account, MT940)
    p2, _ = import_file(session, bank_storage, abn_account, "camt053_002.xml")

    everything = list_transactions(session)
    assert everything.total == 12
    dates = [(r.booking_date, r.id) for r in everything.items]
    assert dates == sorted(dates, reverse=True)
    first = everything.items[0]
    assert first.bank_account_name in {"Zakelijk ING", "Zakelijk ABN"}

    only_ing = list_transactions(session, bank_account_id=ing_account.id)
    assert only_ing.total == 5
    assert list_transactions(session, batch_id=p2.batch_id).total == 7

    assert list_transactions(session, q="kantoor").total >= 2  # name or description, any case
    assert list_transactions(session, q="NL71 INGB 0009 8765 43").total >= 1  # IBAN with spaces
    assert list_transactions(session, q="12,10").total >= 1  # amount, Dutch notation
    assert list_transactions(session, q="1000.00").total >= 1  # amount, plain notation
    assert list_transactions(session, q="bestaatniet").total == 0


def test_list_transactions_pagination(session, bank_storage, ing_account):
    import_file(session, bank_storage, ing_account, MT940)
    page1 = list_transactions(session, page=1, per_page=2)
    page3 = list_transactions(session, page=3, per_page=2)
    beyond = list_transactions(session, page=99, per_page=2)
    assert (len(page1.items), page1.pages, page1.total) == (2, 3, 5)
    assert len(page3.items) == 1
    assert beyond.page == 3


def test_list_batches_only_afgerond(session, bank_storage, ing_account):
    pending = start_import(session, bank_storage, ing_account.id, "p.csv", fixture_bytes(ING_CSV))
    done, _ = import_file(session, bank_storage, ing_account, MT940)
    page = list_batches(session)
    assert [b.id for b in page.items] == [done.batch_id]
    row = page.items[0]
    assert row.bank_account_name == "Zakelijk ING"
    assert row.original_filename == MT940
    assert (row.period_start, row.period_end) == (date(2024, 3, 1), date(2024, 3, 4))
    assert row.new_count == 5 and row.skipped_count == 0
    assert row.format_label == "MT940-bestand" and row.bank_label == "ING"
    assert pending.batch_id not in [b.id for b in page.items]


def test_bank_stats(session, bank_storage, ing_account, abn_account):
    empty = bank_stats(session)
    assert (empty.account_count, empty.transaction_count, empty.last_imported_at) == (2, 0, None)
    import_file(session, bank_storage, ing_account, MT940)
    deactivate(session, abn_account.id)
    stats = bank_stats(session)
    assert stats.account_count == 1  # active only
    assert stats.transaction_count == 5
    assert stats.last_imported_at is not None
