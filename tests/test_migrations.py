from alembic import command
from sqlalchemy import create_engine, text

from tests.conftest import alembic_config


def _version(settings):
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).all()
    engine.dispose()
    return [r[0] for r in rows]


def test_upgrade_downgrade_check(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = alembic_config(test_settings)

    command.upgrade(cfg, "head")
    assert _version(test_settings) == ["0010_opening_balance"]

    command.check(cfg)  # raises on drift

    command.downgrade(cfg, "base")
    assert _version(test_settings) == []
