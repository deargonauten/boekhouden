from types import SimpleNamespace

from sqlalchemy import text

from app.db import Base, create_db_engine, get_session


def test_pragmas_on_fresh_connection(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(test_settings)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    engine.dispose()


def test_get_session_yields_working_session(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(test_settings)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))
    gen = get_session(request)
    session = next(gen)
    assert session.execute(text("SELECT 1")).scalar() == 1
    gen.close()
    engine.dispose()


def test_base_has_metadata():
    assert Base.metadata is not None
