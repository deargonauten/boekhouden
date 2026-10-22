import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import REPO_ROOT, Settings
from app.main import create_app


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "data" / "test.db",
        documents_dir=tmp_path / "data" / "documents",
        bank_dir=tmp_path / "data" / "bank",
    )


def alembic_config(settings: Settings) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return cfg


@pytest.fixture
def client(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(test_settings), "head")
    with TestClient(create_app(test_settings)) as c:
        yield c
