from app.config import Settings


def test_extraction_defaults(monkeypatch):
    for key in ("EXTRACTION_BACKEND", "EXTRACTION_MODEL", "ANTHROPIC_MODEL",
                "EXTRACTION_TIMEOUT_SECONDS", "CLAUDE_CLI_PATH"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.extraction_backend == "auto"
    assert s.extraction_model == "sonnet"
    assert s.anthropic_model == "claude-sonnet-5-5"
    assert s.extraction_timeout_seconds == 180
    assert s.claude_cli_path is None


def test_extraction_env_override(monkeypatch):
    monkeypatch.setenv("EXTRACTION_BACKEND", "anthropic_api")
    monkeypatch.setenv("EXTRACTION_TIMEOUT_SECONDS", "30")
    s = Settings(_env_file=None)
    assert s.extraction_backend == "anthropic_api"
    assert s.extraction_timeout_seconds == 30
