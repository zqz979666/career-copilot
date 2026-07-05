"""Application settings loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    Values are loaded from environment variables (uppercase) or a local `.env`
    file. See `.env.example` for the full list.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- App -----
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_log_level: str = Field(default="INFO")
    app_cors_origins: str = Field(default="http://localhost:3000")

    # ----- Security -----
    jwt_secret_key: str = Field(default="dev-secret-change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=10080)  # 7 days

    # ----- Database -----
    database_url: str = Field(
        default="postgresql+asyncpg://career:career@localhost:5432/career_copilot"
    )
    database_echo: bool = Field(default=False)

    # ----- Redis -----
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ----- LLM -----
    anthropic_api_key: str = Field(default="")
    llm_default_model: str = Field(default="claude-sonnet-4-5")
    llm_max_tokens: int = Field(default=4096)
    llm_temperature: float = Field(default=0.7)
    llm_timeout_seconds: float = Field(default=30.0)
    llm_max_retries: int = Field(default=2)

    # ----- Speech-to-Text (Whisper) -----
    openai_api_key: str = Field(default="")
    whisper_model: str = Field(default="whisper-1")
    whisper_language: str = Field(default="zh")

    # ----- Document parsing -----
    document_max_upload_bytes: int = Field(default=10 * 1024 * 1024)  # 10 MB
    document_max_chars: int = Field(default=20_000)

    # ----- Rate Limit -----
    rate_limit_anon_per_hour: int = Field(default=5)
    rate_limit_user_per_hour: int = Field(default=60)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
