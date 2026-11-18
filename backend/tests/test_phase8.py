from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.main import app
from app.providers import openrouter


def test_chat_and_embedding_model_settings_are_independent():
    settings = Settings(
        _env_file=None,
        openrouter_chat_model="openrouter/free",
        openrouter_embedding_model="nvidia/nemotron-3-embed-1b:free",
    )
    assert settings.openrouter_chat_model == "openrouter/free"
    assert settings.openrouter_embedding_model == "nvidia/nemotron-3-embed-1b:free"
    assert settings.embedding_dimensions == 2048


@pytest.mark.asyncio
async def test_openrouter_chat_uses_configured_model_and_parses_text(monkeypatch):
    captured = {}

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Supported result [1]."))]
            )

    class AsyncClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(
        openrouter,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            openrouter_api_key="test-only-key",
            openrouter_chat_model="openrouter/free",
        ),
    )
    monkeypatch.setattr(openrouter, "AsyncOpenAI", AsyncClient)
    monkeypatch.setattr(openrouter, "OpenAI", lambda **_kwargs: object())
    result = await openrouter.OpenRouterProvider().generate(
        question="What is supported?", context="[1] A saved fact."
    )
    assert result == "Supported result [1]."
    assert captured["model"] == "openrouter/free"
    assert "Never infer facts absent" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_openrouter_rejects_empty_chat_response(monkeypatch):
    class Completions:
        async def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  "))])

    class AsyncClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(
        openrouter,
        "get_settings",
        lambda: Settings(_env_file=None, openrouter_api_key="test-only-key"),
    )
    monkeypatch.setattr(openrouter, "AsyncOpenAI", AsyncClient)
    monkeypatch.setattr(openrouter, "OpenAI", lambda **_kwargs: object())
    with pytest.raises(ProviderError, match="empty response"):
        await openrouter.OpenRouterProvider().generate(question="Question", context="[1] Source.")


def test_ai_health_distinguishes_configuration_from_live_connectivity():
    response = TestClient(app).get("/health/ai")
    assert response.status_code == 200
    body = response.json()
    assert body["chat_model_configured"] is True
    assert body["embedding_model_configured"] is True
    assert body["provider_connectivity"] == "not_tested"
    assert body["chat_generation_test"] == "not_tested"



def test_profile_update_schema_cleans_name_and_rejects_email_changes():
    from pydantic import ValidationError

    from app.schemas.auth import ProfileUpdate

    assert ProfileUpdate(display_name="  Krishna   Kumar ").display_name == "Krishna Kumar"
    assert ProfileUpdate(display_name="   ").display_name is None
    with pytest.raises(ValidationError):
        ProfileUpdate(display_name="x" * 81)
    with pytest.raises(ValidationError):
        ProfileUpdate(display_name="ok", email="other@example.com")
    with pytest.raises(ValidationError):
        ProfileUpdate(display_name="bad\x00name")


def test_profile_endpoint_requires_authentication():
    response = TestClient(app).patch("/api/v1/auth/me", json={"display_name": "Someone"})
    assert response.status_code == 401


def test_conversation_titles_are_short_and_rename_requires_auth():
    from uuid import uuid4

    from app.services.titles import generate_title

    library = [(uuid4(), "Project Atlas - Initial Budget", {"project": "Project Atlas"})]
    assert generate_title("What's the budget revision for Project Atlas?", library).endswith("Budget Revision")
    assert generate_title("What's the budget revision for Project Atlas?", library).startswith("Project Atlas")
    assert generate_title("please give my portfolio website") == "Portfolio Website"
    assert len(generate_title("x " * 100)) <= 60
    response = TestClient(app).patch("/api/v1/conversations/00000000-0000-0000-0000-000000000000", json={"title": "A"})
    assert response.status_code == 401
