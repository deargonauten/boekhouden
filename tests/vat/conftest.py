import pytest
from sqlalchemy.orm import Session

from app.db import create_db_engine
from tests.conftest import migrate_to_head


@pytest.fixture
def engine(test_settings):
    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    migrate_to_head(test_settings)
    engine = create_db_engine(test_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s
