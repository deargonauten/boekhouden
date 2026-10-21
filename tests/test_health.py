from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import create_app


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_db_failure_returns_503(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        # Point the engine at an unusable path (parent directory does not exist).
        app.state.engine = create_engine(
            f"sqlite:///{test_settings.database_path.parent / 'missing' / 'x.db'}"
        )
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}
