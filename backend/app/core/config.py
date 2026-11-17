from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Knowledge Inbox"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str | None = None
    jwt_secret_key: str | None = None
    jwt_expire_minutes: int = Field(default=60, gt=0, le=1440)
    jwt_issuer: str = "ai-knowledge-inbox"
    migration_owner_email: str | None = None
    migration_owner_password_hash: str | None = None
    llm_provider: str = "openrouter"
    openrouter_api_key: str | None = None
    openrouter_chat_model: str | None = Field(
        default="openrouter/free",
        validation_alias=AliasChoices("OPENROUTER_CHAT_MODEL", "OPENROUTER_MODEL"),
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = Field(default=45, gt=0, le=180)
    openrouter_temperature: float = Field(default=0.2, ge=0, le=2)
    openrouter_embedding_model: str = Field(
        default="nvidia/nemotron-3-embed-1b:free",
        validation_alias=AliasChoices("OPENROUTER_EMBEDDING_MODEL", "EMBEDDING_MODEL"),
    )
    embedding_dimensions: int = Field(default=2048, gt=0)
    app_timezone: str = "Asia/Kolkata"
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    retrieval_top_k: int = Field(default=5, gt=0)
    retrieval_min_score: float = Field(default=0.15, ge=0, le=1)
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("llm_provider")
    @classmethod
    def only_openrouter(cls, value: str) -> str:
        if value.lower() != "openrouter":
            raise ValueError("Only the OpenRouter provider is supported")
        return "openrouter"

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_is_unconfigured(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return str(value).strip()

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_below_chunk_size(cls, value: int, info):
        if value >= info.data.get("chunk_size", 800):
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return value

    @field_validator("app_timezone")
    @classmethod
    def valid_iana_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("app_timezone must be a valid IANA timezone") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
