"""Application settings, loaded from environment variables or a .env file.

Secrets never live in the repository. Copy `.env.example` to `.env` at the
repository root and fill in real values.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "d_clinic"
    pg_user: str = "postgres"
    pg_password: str = Field(default="", repr=False)

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Synthetic data
    synth_seed: int = 42
    synth_patients: int = 6000
    synth_out_dir: Path = REPO_ROOT / "data" / "synth" / "out"

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        """SQLAlchemy URL. Password is URL-encoded so symbols such as `$` are safe."""
        return (
            f"postgresql+psycopg://{quote_plus(self.pg_user)}:{quote_plus(self.pg_password)}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )


settings = Settings()
