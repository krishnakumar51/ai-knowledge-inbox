from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.routes.items import _item_error_status
from app.core.config import Settings
from app.core.exceptions import AppError, ServiceUnavailableError
from app.core.time import as_user_timezone, parse_import_timestamp
from app.schemas.common import APIModel
from app.schemas.dataset import HistoricalDataset
from app.services import embeddings


def test_import_timestamp_interprets_naive_values_as_ist_and_offsets_as_absolute():
    assert parse_import_timestamp("2026-11-10T10:00:00").isoformat() == "2026-11-10T04:30:00+00:00"
    assert parse_import_timestamp("2026-11-10T10:00:00+05:30").isoformat() == "2026-11-10T04:30:00+00:00"
    assert parse_import_timestamp("2026-11-10T04:30:00Z").isoformat() == "2026-11-10T04:30:00+00:00"


def test_import_timestamp_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_import_timestamp("not-a-timestamp")
    with pytest.raises(TypeError):
        parse_import_timestamp(123)  # type: ignore[arg-type]


def test_api_model_serializes_datetimes_in_ist():
    class Response(APIModel):
        created_at: datetime

    value = Response(created_at=datetime(2026, 11, 10, 4, 30, tzinfo=UTC)).model_dump(mode="json")
    assert value["created_at"] == "2026-11-10T10:00:00+05:30"
    assert as_user_timezone(datetime(2026, 11, 10, 4, 30, tzinfo=UTC)).utcoffset().total_seconds() == 19800


def test_historical_dataset_normalizes_naive_timestamps_and_rejects_duplicate_ids():
    raw = {
        "dataset_id": "historical-test",
        "user_email": "test@example.com",
        "items": [
            {
                "external_id": "note-1",
                "source_type": "note",
                "content": "A historical fact",
                "created_at": "2026-11-10T10:00:00",
            }
        ],
    }
    parsed = HistoricalDataset.model_validate(raw)
    assert parsed.items[0].created_at.isoformat() == "2026-11-10T04:30:00+00:00"
    raw["items"].append(raw["items"][0])
    with pytest.raises(ValidationError, match="unique"):
        HistoricalDataset.model_validate(raw)


def test_document_and_query_embeddings_use_same_provider(monkeypatch):
    class Provider:
        def embed_texts(self, texts):
            self.texts = texts
            return [[0.25] * 2048 for _ in texts]

    provider = Provider()
    monkeypatch.setattr(embeddings, "get_llm_provider", lambda: provider)
    service = embeddings.EmbeddingService()
    assert service.embed_text("saved note") == [0.25] * 2048
    assert service.embed_query("search question") == [0.25] * 2048
    assert provider.texts == ["search question"]


def test_phase7_model_defaults_match_requested_provider_ids():
    settings = Settings()
    assert settings.openrouter_chat_model == "openrouter/free"
    assert settings.openrouter_embedding_model == "nvidia/nemotron-3-embed-1b:free"
    assert settings.embedding_dimensions == 2048
    assert settings.app_timezone == "Asia/Kolkata"


def test_item_routes_preserve_provider_failure_status_and_validation_status():
    assert _item_error_status(ServiceUnavailableError("embedding service unavailable")) == 503
    assert _item_error_status(AppError("An item must have processed chunks before it can be activated")) == 422
    assert _item_error_status(AppError("Item not found")) == 404
