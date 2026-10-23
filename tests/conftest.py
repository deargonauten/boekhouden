import shutil
import tempfile
from pathlib import Path

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


_TEMPLATE: Path | None = None


def _template_db() -> Path:
    """A database migrated to head, built once per process (so once per xdist worker)."""
    global _TEMPLATE
    if _TEMPLATE is None:
        root = Path(tempfile.mkdtemp(prefix="boekhouden-template-"))
        settings = Settings(
            _env_file=None, database_path=root / "template.db",
            documents_dir=root / "documents", bank_dir=root / "bank",
        )
        command.upgrade(alembic_config(settings), "head")
        _TEMPLATE = settings.database_path
    return _TEMPLATE


def migrate_to_head(settings: Settings) -> None:
    """Same result as `alembic upgrade head`, but copies the pre-migrated template database."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_template_db(), settings.database_path)


@pytest.fixture
def client(test_settings):
    migrate_to_head(test_settings)
    with TestClient(create_app(test_settings)) as c:
        yield c
