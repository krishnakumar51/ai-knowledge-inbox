import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.db.session import get_engine, normalize_database_url


def test_openrouter_is_the_only_llm_provider():
    assert Settings(llm_provider="openrouter").llm_provider == "openrouter"
    with pytest.raises(ValidationError):
        Settings(llm_provider="groq")


def test_provider_can_be_selected_without_credentials():
    settings = Settings(openrouter_api_key=None, openrouter_chat_model=None)
    assert settings.llm_provider == "openrouter"
    assert settings.openrouter_api_key is None


def test_database_is_optional_and_blank_values_are_unconfigured():
    assert Settings(database_url=None).database_url is None
    assert Settings(database_url="").database_url is None


def test_postgres_urls_normalize_to_asyncpg_with_ssl_mode():
    url = normalize_database_url("postgresql://reader:secret@db.example.test/knowledge?sslmode=require")
    assert url.startswith("postgresql+asyncpg://")
    assert "ssl=require" in url


def test_asyncpg_rejects_unsupported_channel_binding_instead_of_ignoring_it():
    with pytest.raises(ServiceUnavailableError, match="does not support the channel_binding"):
        normalize_database_url(
            "postgresql://reader:secret@db.example.test/knowledge?sslmode=require&channel_binding=require"
        )


def test_database_engine_requires_explicit_configuration(monkeypatch):
    from app.db import session

    monkeypatch.setattr(session, "get_settings", lambda: Settings(database_url=None))
    with pytest.raises(ServiceUnavailableError, match="DATABASE_URL is not configured"):
        get_engine()
