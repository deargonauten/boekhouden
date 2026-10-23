import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from tests.conftest import alembic_config


def _engine(settings):
    return create_engine(settings.database_url)


def test_upgrade_from_0014_and_downgrade(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)
    command.upgrade(cfg, "0014_btw_aangifte")
    engine = _engine(test_settings)
    assert "email_message" not in inspect(engine).get_table_names()

    command.upgrade(cfg, "0015_email_intake")
    assert "email_message" in inspect(engine).get_table_names()
    command.check(cfg)

    command.downgrade(cfg, "0014_btw_aangifte")
    names = inspect(engine).get_table_names()
    assert "email_message" not in names and "vat_return" in names
    engine.dispose()


def _insert(conn, key="k", outcome="opgeslagen"):
    conn.execute(
        text(
            "INSERT INTO email_message (message_key, received_at, processed_at, outcome) "
            "VALUES (:k, '2026-01-01', '2026-01-01', :o)"
        ),
        {"k": key, "o": outcome},
    )


def test_constraints(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    engine = _engine(test_settings)
    with engine.begin() as conn:
        _insert(conn)
        row = conn.execute(text("SELECT documents_new, moved FROM email_message")).one()
    assert tuple(row) == (0, 0)
    with pytest.raises(DatabaseError):
        with engine.begin() as conn:
            _insert(conn)  # unique key
    with pytest.raises(DatabaseError):
        with engine.begin() as conn:
            _insert(conn, key="k2", outcome="onbekend")
    engine.dispose()
