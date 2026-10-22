"""Migration 0009: bank_account, bank_import_batch, bank_transaction and append-only triggers."""

import sqlite3

import pytest
from alembic import command

from tests.conftest import alembic_config


@pytest.fixture
def db(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    conn = sqlite3.connect(test_settings.database_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def add_account(db, iban="NL20INGB0001234567", code="1210", bank="ing"):
    acc = one(db, "SELECT id FROM account WHERE code=?", code)
    jr = one(db, "SELECT id FROM journal WHERE code='BANK'")
    db.execute(
        "INSERT INTO bank_account(name, iban, bank, account_id, journal_id, created_at) "
        "VALUES ('ING', ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (iban, bank, acc, jr),
    )
    return one(db, "SELECT id FROM bank_account WHERE iban=?", iban)


def add_batch(db, ba, status="voorbeeld", fmt="mt940"):
    db.execute(
        "INSERT INTO bank_import_batch(bank_account_id, status, original_filename, sha256, ext, size, "
        "detected_format, created_at) VALUES (?, ?, 'a.sta', ?, 'sta', 10, ?, CURRENT_TIMESTAMP)",
        (ba, status, "a" * 64, fmt),
    )
    return one(db, "SELECT max(id) FROM bank_import_batch")


def add_tx(db, ba, batch, amount=-350, key="k1", occ=1, **kw):
    cols = {
        "bank_account_id": ba,
        "import_batch_id": batch,
        "booking_date": "2024-03-04",
        "amount_cents": amount,
        "dedupe_key": key,
        "occurrence": occ,
        "raw": "raw",
        "created_at": "2024-03-05 10:00:00",
        **kw,
    }
    db.execute(
        f"INSERT INTO bank_transaction({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )
    return one(db, "SELECT max(id) FROM bank_transaction")


def test_tables_and_head(db):
    assert {"bank_account", "bank_import_batch", "bank_transaction"} <= tables(db)
    assert one(db, "SELECT version_num FROM alembic_version") == "0009_bank_import"


def test_bank_account_constraints(db):
    add_account(db)
    with pytest.raises(sqlite3.IntegrityError):  # IBAN unique
        add_account(db, code="1220")
    with pytest.raises(sqlite3.IntegrityError):  # one bankrekening per grootboekrekening
        add_account(db, iban="NL91ABNA0417164300")
    with pytest.raises(sqlite3.IntegrityError):  # bank value check
        add_account(db, iban="NL91ABNA0417164300", code="1220", bank="nepbank")
    acc = one(db, "SELECT id FROM bank_account")
    assert one(db, "SELECT is_active FROM bank_account WHERE id=?", acc) == 1


def test_batch_constraints(db):
    ba = add_account(db)
    add_batch(db, ba)
    with pytest.raises(sqlite3.IntegrityError):
        add_batch(db, ba, status="klaar")
    with pytest.raises(sqlite3.IntegrityError):
        add_batch(db, ba, fmt="pdf")
    assert one(db, "SELECT maybe_duplicate_count FROM bank_import_batch") == 0


def test_transaction_constraints(db):
    ba = add_account(db)
    batch = add_batch(db, ba)
    tx = add_tx(db, ba, batch)
    assert one(db, "SELECT currency FROM bank_transaction WHERE id=?", tx) == "EUR"
    assert one(db, "SELECT status FROM bank_transaction WHERE id=?", tx) == "nieuw"
    assert one(db, "SELECT description FROM bank_transaction WHERE id=?", tx) == ""
    with pytest.raises(sqlite3.IntegrityError):  # zero amount
        add_tx(db, ba, batch, amount=0, key="k2")
    with pytest.raises(sqlite3.IntegrityError):  # EUR only
        add_tx(db, ba, batch, key="k3", currency="USD")
    with pytest.raises(sqlite3.IntegrityError):  # status values
        add_tx(db, ba, batch, key="k4", status="weg")
    with pytest.raises(sqlite3.IntegrityError):  # unique (rekening, key, occurrence)
        add_tx(db, ba, batch, key="k1", occ=1)
    add_tx(db, ba, batch, key="k1", occ=2)  # next occurrence is fine


def test_transaction_requires_existing_parents(db):
    with pytest.raises(sqlite3.IntegrityError):
        add_tx(db, 999, 999)


def test_append_only_triggers(db):
    ba = add_account(db)
    batch = add_batch(db, ba)
    tx = add_tx(db, ba, batch)
    for column, value in [
        ("amount_cents", 1),
        ("booking_date", "2024-01-01"),
        ("description", "x"),
        ("dedupe_key", "zzz"),
        ("raw", "changed"),
        ("counterparty_iban", "NL02ABNA0123456789"),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
            db.execute(f"UPDATE bank_transaction SET {column}=? WHERE id=?", (value, tx))
    with pytest.raises(sqlite3.IntegrityError, match="onveranderlijk"):
        db.execute("DELETE FROM bank_transaction WHERE id=?", (tx,))
    assert one(db, "SELECT amount_cents FROM bank_transaction WHERE id=?", tx) == -350


def test_status_and_journal_link_may_change(db):
    ba = add_account(db)
    batch = add_batch(db, ba)
    tx = add_tx(db, ba, batch)
    db.execute("UPDATE bank_transaction SET status='genegeerd' WHERE id=?", (tx,))
    assert one(db, "SELECT status FROM bank_transaction WHERE id=?", tx) == "genegeerd"
    # a null-to-null update of an unrelated column is not a change
    db.execute("UPDATE bank_transaction SET value_date=value_date WHERE id=?", (tx,))


def test_downgrade_and_upgrade_again(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0008_purchase_booking")
    conn = sqlite3.connect(test_settings.database_path)
    assert not {"bank_account", "bank_import_batch", "bank_transaction"} & tables(conn)
    conn.close()
    command.upgrade(cfg, "head")
    conn = sqlite3.connect(test_settings.database_path)
    assert "bank_transaction" in tables(conn)
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"bank_transaction_no_delete", "bank_transaction_no_update"} <= triggers
    conn.close()
