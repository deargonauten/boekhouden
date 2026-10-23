from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve(path: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_path: Path = Path("data/boekhouden.db")
    documents_dir: Path = Path("data/documents")
    bank_dir: Path = Path("data/bank")
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_reload: bool = True
    anthropic_api_key: SecretStr | None = None
    # Invoice extraction (see app/domain/extraction/extractors).
    extraction_backend: Literal["auto", "claude_cli", "anthropic_api"] = "auto"
    extraction_model: str = "sonnet"  # alias for the `claude` CLI
    anthropic_model: str = "claude-sonnet-5-5"  # model id for the API backend
    extraction_timeout_seconds: int = 180
    claude_cli_path: str | None = None
    # Email intake (see app/domain/email_intake). Credentials only live in .env.
    imap_host: str | None = None
    imap_port: int = 993  # implicit TLS
    imap_user: str | None = None
    imap_password: SecretStr | None = None
    imap_folder: str = "INBOX"
    imap_processed_folder: str = "Verwerkt"
    imap_poll_interval_minutes: int = 0  # 0 = no background polling
    imap_max_messages_per_run: int = 50
    imap_timeout_seconds: int = 30

    @field_validator("imap_poll_interval_minutes")
    @classmethod
    def _check_poll_interval(cls, value: int) -> int:
        if value != 0 and not 1 <= value <= 1440:
            raise ValueError(
                "IMAP_POLL_INTERVAL_MINUTES moet 0 (uit) zijn of een aantal minuten "
                "tussen 1 en 1440. Pas de waarde aan in je .env-bestand."
            )
        return value

    def model_post_init(self, __context) -> None:
        # Resolve relative paths against the repo root so cwd does not matter.
        self.database_path = _resolve(self.database_path)
        self.documents_dir = _resolve(self.documents_dir)
        self.bank_dir = _resolve(self.bank_dir)

    @property
    def imap_configured(self) -> bool:
        return bool(
            self.imap_host
            and self.imap_user
            and self.imap_password
            and self.imap_password.get_secret_value()
        )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_data_dirs(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    settings.bank_dir.mkdir(parents=True, exist_ok=True)
