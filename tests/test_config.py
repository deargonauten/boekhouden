from pathlib import Path

from app.config import REPO_ROOT, Settings, ensure_data_dirs, get_settings


def test_defaults(monkeypatch):
    for key in ("DATABASE_PATH", "DOCUMENTS_DIR", "APP_HOST", "APP_PORT", "APP_RELOAD"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.database_path == REPO_ROOT / "data" / "boekhouden.db"
    assert s.documents_dir == REPO_ROOT / "data" / "documents"
    assert (s.app_host, s.app_port, s.app_reload) == ("127.0.0.1", 8000, True)
    assert s.anthropic_api_key is None


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("APP_PORT", "9000")
    s = Settings(_env_file=None)
    assert s.database_path == tmp_path / "x.db"
    assert s.app_port == 9000


def test_relative_path_resolved_against_repo_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = Settings(_env_file=None, database_path=Path("foo/bar.db"))
    assert s.database_path == REPO_ROOT / "foo" / "bar.db"


def test_ensure_data_dirs_idempotent(tmp_path):
    s = Settings(
        _env_file=None,
        database_path=tmp_path / "a" / "db.sqlite",
        documents_dir=tmp_path / "b" / "docs",
    )
    ensure_data_dirs(s)
    ensure_data_dirs(s)
    assert (tmp_path / "a").is_dir()
    assert (tmp_path / "b" / "docs").is_dir()


def test_api_key_not_leaked_in_repr():
    s = Settings(_env_file=None, anthropic_api_key="sk-secret-123")
    assert "sk-secret-123" not in repr(s)
    assert "sk-secret-123" not in str(s)


def test_get_settings_cached():
    assert get_settings() is get_settings()
