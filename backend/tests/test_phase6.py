from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.core import security
from app.core.config import Settings
from app.main import app
from app.services.generation import temporal_intent
from app.services.retrieval import RetrievalService


class DummyEmbeddings:
    def embed_query(self, _query):
        return [0.0] * 2048


def test_scrypt_password_hash_round_trip_and_rejects_wrong_password():
    encoded = security.hash_password("a-long-test-password")
    assert encoded.startswith("scrypt$")
    assert security.verify_password("a-long-test-password", encoded)
    assert not security.verify_password("different-password", encoded)


def test_access_token_valid_tampered_and_expired(monkeypatch):
    monkeypatch.setattr(
        security, "get_settings", lambda: Settings(jwt_secret_key="x" * 48, jwt_expire_minutes=1)
    )
    user_id = uuid4()
    token = security.create_access_token(user_id)
    assert security.decode_access_token(token) == user_id
    with pytest.raises(ValueError):
        security.decode_access_token(token + "x")
    monkeypatch.setattr(security.time, "time", lambda: datetime.now(UTC).timestamp() + 120)
    with pytest.raises(ValueError, match="Invalid or expired"):
        security.decode_access_token(token)


def test_temporal_intent_recognizes_current_historical_and_timeline():
    assert temporal_intent("What is my current budget?")[0] == "current"
    assert temporal_intent("What was my budget on 2025-11-10") == ("historical", date(2025, 11, 10))
    assert temporal_intent("Show the budget timeline")[0] == "timeline"
    assert temporal_intent("What was my budget last month", date(2026, 11, 17)) == (
        "historical",
        date(2026, 10, 31),
    )


@pytest.mark.asyncio
async def test_current_reranking_prefers_recent_relevant_fact_not_unrelated_recent(monkeypatch):
    from app.models import Chunk, Item
    from app.models.item import ItemStatus, SourceType
    from app.services import generation
    from app.services.generation import QueryService

    old = Item(
        id=uuid4(),
        title="Older budget",
        source_type=SourceType.note,
        status=ItemStatus.ACTIVE,
        created_at=datetime(2025, 11, 10, tzinfo=UTC),
        effective_at=datetime(2025, 11, 10, tzinfo=UTC),
    )
    new = Item(
        id=uuid4(),
        title="Newer budget",
        source_type=SourceType.note,
        status=ItemStatus.ACTIVE,
        created_at=datetime(2025, 11, 15, tzinfo=UTC),
        effective_at=datetime(2025, 11, 15, tzinfo=UTC),
    )
    unrelated = Item(
        id=uuid4(),
        title="Recent unrelated",
        source_type=SourceType.note,
        status=ItemStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    rows = [
        (
            Chunk(id=uuid4(), item_id=item.id, chunk_index=0, content=item.title, embedding=[0.0] * 2048),
            item,
            score,
        )
        for item, score in ((old, 0.82), (new, 0.80), (unrelated, 0.21))
    ]

    class Retrieval:
        async def retrieve(self, *_args, effective_before=None, **_kwargs):
            if effective_before is None:
                return rows
            return [row for row in rows if (row[1].effective_at or row[1].created_at) < effective_before]

    class Provider:
        async def generate(self, *, question, context, history=None):
            self.context = context
            return "Latest supported result [1]."

    provider = Provider()
    monkeypatch.setattr(generation, "get_llm_provider", lambda: provider)
    response = await QueryService(DummyEmbeddings(), Retrieval()).answer(
        object(), uuid4(), "What is my latest budget?"
    )
    assert response.sources[0].title == "Newer budget"
    assert response.sources[1].title == "Older budget"
    assert response.sources[2].title == "Recent unrelated"


@pytest.mark.asyncio
async def test_historical_and_timeline_queries_keep_older_sources(monkeypatch):
    from app.models import Chunk, Item
    from app.models.item import ItemStatus, SourceType
    from app.services import generation
    from app.services.generation import QueryService

    def result(title, day):
        item = Item(
            id=uuid4(),
            title=title,
            source_type=SourceType.note,
            status=ItemStatus.ACTIVE,
            created_at=datetime(2025, 11, day, tzinfo=UTC),
            effective_at=datetime(2025, 11, day, tzinfo=UTC),
        )
        return (
            Chunk(id=uuid4(), item_id=item.id, chunk_index=0, content=title, embedding=[0.0] * 2048),
            item,
            0.8,
        )

    rows = [result("Older budget", 10), result("Newer budget", 15)]

    class Retrieval:
        async def retrieve(self, *_args, effective_before=None, **_kwargs):
            if effective_before is None:
                return rows
            return [row for row in rows if (row[1].effective_at or row[1].created_at) < effective_before]

    class Provider:
        async def generate(self, *, question, context, history=None):
            return "Timeline [1] [2]."

    monkeypatch.setattr(generation, "get_llm_provider", Provider)
    service = QueryService(DummyEmbeddings(), Retrieval())
    historical = await service.answer(object(), uuid4(), "What was my budget on 2025-11-10?")
    assert [source.title for source in historical.sources] == ["Older budget"]
    timeline = await service.answer(object(), uuid4(), "Show a timeline of my budget changes")
    assert [source.title for source in timeline.sources] == ["Older budget", "Newer budget"]
    assert temporal_intent("What was the budget on November 10?", date(2026, 11, 17)) == (
        "historical",
        date(2026, 11, 10),
    )


@pytest.mark.asyncio
async def test_both_retrieval_statements_filter_by_user_in_sql():
    class Result:
        def all(self):
            return []

    class CaptureSession:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

    db = CaptureSession()
    await RetrievalService().retrieve(db, uuid4(), [0.0] * 2048, "budget", 5)
    assert len(db.statements) == 2
    for statement in db.statements:
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        assert "items.user_id" in compiled


def test_health_and_openapi_load_without_database_or_ai_calls():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/api/v1/items").status_code == 401

