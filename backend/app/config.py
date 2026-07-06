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
    # Lightweight model used by the Master Agent for intent classification
    # (rule-miss fallback) and other cheap structured tasks.
    llm_intent_model: str = Field(default="claude-haiku-4-5")
    llm_max_tokens: int = Field(default=4096)
    llm_temperature: float = Field(default=0.7)
    llm_timeout_seconds: float = Field(default=30.0)
    llm_max_retries: int = Field(default=2)

    # ----- Embeddings (Profile semantic search via pgvector) -----
    # Uses OpenAI text-embedding-3-small (1536 dims). When no OpenAI key is
    # configured the Profile Engine degrades gracefully to keyword/recency
    # retrieval and stores NULL embeddings.
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dim: int = Field(default=1536)
    embedding_enabled: bool = Field(default=True)

    # ----- Speech-to-Text (Whisper) -----
    openai_api_key: str = Field(default="")
    whisper_model: str = Field(default="whisper-1")
    whisper_language: str = Field(default="zh")

    # ----- Vision (screenshot OCR via Claude Vision) -----
    vision_model: str = Field(default="claude-sonnet-4-5")
    vision_max_image_bytes: int = Field(default=5 * 1024 * 1024)  # 5 MB

    # ----- Resume Studio -----
    resume_max_versions: int = Field(default=20)
    # Number of most-relevant profile entries fed to the Resume Agent.
    resume_retrieval_top_k: int = Field(default=40)

    # ----- Document parsing -----
    document_max_upload_bytes: int = Field(default=10 * 1024 * 1024)  # 10 MB
    document_max_chars: int = Field(default=20_000)

    # ----- Rate Limit -----
    rate_limit_anon_per_hour: int = Field(default=5)
    rate_limit_user_per_hour: int = Field(default=60)

    # ----- v0.8 GitHub OAuth + Webhooks -----
    # Set these to actually enable the integration; when blank the endpoints
    # respond with a friendly 503 rather than crashing on boot.
    github_client_id: str = Field(default="")
    github_client_secret: str = Field(default="")
    github_oauth_scopes: str = Field(default="read:user user:email repo")
    github_webhook_secret: str = Field(default="")
    # Where the OAuth callback lives. In prod, this is your public API URL.
    github_oauth_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/oauth/github/callback"
    )
    # Fernet key (base64 32-byte) used to encrypt access/refresh tokens at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # When unset we DERIVE a stable key from JWT_SECRET_KEY (dev only).
    integration_encryption_key: str = Field(default="")

    # ----- v0.8 GitHub sync (Adapter) -----
    github_api_base: str = Field(default="https://api.github.com")
    # Max PRs to pull per manual sync call. Keeps costs bounded.
    github_sync_max_prs: int = Field(default=30)
    # Where PR-derived Profile entries land. Bound to source_type = "github".
    github_pr_body_max_chars: int = Field(default=500)

    # ----- v0.8 Master Agent parallel dispatch -----
    master_parallel_enabled: bool = Field(default=True)

    # ----- v1.0 feature gates / event bus -----
    analysis_agent_enabled: bool = Field(default=True)
    job_agent_enabled: bool = Field(default=True)
    trust_ladder_l2_enabled: bool = Field(default=True)
    # direct = legacy direct ingest; dual = direct + event publish; event = event only
    sync_event_mode: str = Field(default="dual")

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
