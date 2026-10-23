import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from tests.conftest import alembic_config

NEW_TABLES = {"vat_setting", "vat_return", "vat_entry_contact"}


def _engine(settings):
    return create_engine(settings.database_url)


def test_upgrade_from_0013_and_downgrade(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "0013_bank_match_sales")
    engine = _engine(test_settings)
    assert not NEW_TABLES & set(inspect(engine).get_table_names())

    command.upgrade(cfg, "0014_btw_aangifte")
    assert NEW_TABLES <= set(inspect(engine).get_table_names())
    # no command.check here: models are ahead of this revision (checked at head in test_migrations)

    command.downgrade(cfg, "0013_bank_match_sales")
    assert not NEW_TABLES & set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        triggers = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'vat_return%'")
        ).all()
    assert triggers == []
    engine.dispose()


def _insert_return(conn, number=1):
    conn.execute(text(
        "INSERT INTO vat_return (year, kind, number, start_date, end_date, status, filed_on, filed_at, "
        "snapshot_json, total_cents) VALUES (2026, 'quarter', :n, '2026-01-01', '2026-03-31', 'ingediend', "
        "'2026-04-10', '2026-04-10 10:00:00', '{}', 100)"), {"n": number})


def test_triggers_and_constraints(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    engine = _engine(test_settings)
    with engine.begin() as conn:
        _insert_return(conn)
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM vat_return"))
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE vat_return SET total_cents = 1"))
    with engine.begin() as conn:
        conn.execute(text("UPDATE vat_return SET reference = 'R1'"))
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE vat_return SET reference = 'R2'"))
    with pytest.raises(DatabaseError):  # unique period
        with engine.begin() as conn:
            _insert_return(conn)
    with pytest.raises(DatabaseError):  # quarter number out of range
        with engine.begin() as conn:
            _insert_return(conn, number=5)
    with pytest.raises(DatabaseError):  # single settings row
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO vat_setting (id, frequency, updated_at) VALUES (2, 'quarter', '2026-01-01')"))
    with pytest.raises(DatabaseError):  # frequency check
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO vat_setting (id, frequency, updated_at) VALUES (1, 'week', '2026-01-01')"))
    engine.dispose()
