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

    # LLM gateway (Step 4). `none` = templated summary only.
    # Local laptop: LLM_PROVIDER=ollama. Live VPS: LLM_PROVIDER=openai.
    llm_provider: str = "none"  # none | ollama | openai
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:3b"
    openai_api_key: str = Field(default="", repr=False)
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 30.0
    llm_max_tokens: int = 250

    # Embeddings for the ready-reckoner (Step 6). `tfidf` = local bag-of-words, no API.
    # Laptop: EMBEDDING_PROVIDER=ollama and `ollama pull nomic-embed-text`.
    # Live VPS: EMBEDDING_PROVIDER=openai (same OPENAI_API_KEY as chat).
    embedding_provider: str = "tfidf"  # tfidf | ollama | openai
    ollama_embed_model: str = "nomic-embed-text"
    openai_embed_model: str = "text-embedding-3-small"

    # Browser origins allowed to call this API (comma-separated).
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "https://clinic.1960heritage.com,"
        "https://d-clinic-one.vercel.app"
    )

    @computed_field  # type: ignore[misc]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        """SQLAlchemy URL. Password is URL-encoded so symbols such as `$` are safe."""
        return (
            f"postgresql+psycopg://{quote_plus(self.pg_user)}:{quote_plus(self.pg_password)}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )


settings = Settings()
