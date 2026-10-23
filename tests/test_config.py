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


def test_imap_defaults_and_not_configured(monkeypatch):
    for key in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_POLL_INTERVAL_MINUTES"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert (s.imap_port, s.imap_folder, s.imap_processed_folder) == (993, "INBOX", "Verwerkt")
    assert (s.imap_poll_interval_minutes, s.imap_max_messages_per_run, s.imap_timeout_seconds) == (0, 50, 30)
    assert s.imap_configured is False


def test_imap_configured_needs_host_user_password():
    full = dict(imap_host="h", imap_user="u", imap_password="p")
    assert Settings(_env_file=None, **full).imap_configured
    for missing in full:
        assert not Settings(_env_file=None, **{k: v for k, v in full.items() if k != missing}).imap_configured


def test_imap_password_not_leaked():
    s = Settings(_env_file=None, imap_password="imap-secret-1")
    assert "imap-secret-1" not in repr(s) and "imap-secret-1" not in str(s)


def test_imap_poll_interval_validation():
    import pytest
    from pydantic import ValidationError

    for ok in (0, 1, 15, 1440):
        assert Settings(_env_file=None, imap_poll_interval_minutes=ok).imap_poll_interval_minutes == ok
    for bad in (-1, 1441):
        with pytest.raises(ValidationError, match="IMAP_POLL_INTERVAL_MINUTES"):
            Settings(_env_file=None, imap_poll_interval_minutes=bad)
