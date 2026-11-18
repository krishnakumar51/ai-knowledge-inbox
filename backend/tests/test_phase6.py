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
    # ranking is verified on the context the model saw; only the cited source is returned
    ctx = provider.context
    assert ctx.index("Newer budget") < ctx.index("Older budget") < ctx.index("Recent unrelated")
    assert [source.title for source in response.sources] == ["Newer budget"]


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
    # scope lookup + vector branch + keyword branch, every one restricted to the user
    assert len(db.statements) == 3
    for statement in db.statements:
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        assert "items.user_id" in compiled


def test_health_and_openapi_load_without_database_or_ai_calls():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/api/v1/items").status_code == 401



def test_explicit_date_beats_planned_wording_and_year_less_near_future_dates():
    today = date(2026, 11, 18)
    assert temporal_intent("What was the planned launch date as of November 5, 2026?", today) == (
        "historical",
        date(2026, 11, 5),
    )
    # Upcoming (near-future) dates stay in the current year instead of rolling back.
    assert temporal_intent("What retrieval target applies to the November 25 evaluation?", today) == (
        "historical",
        date(2026, 11, 25),
    )
    assert temporal_intent("Who owned the work in September?", today) == ("historical", date(2026, 9, 30))
    assert temporal_intent("What is the planned Ads budget for December?", today)[0] == "future"
    assert temporal_intent("What was the original planned launch date?", today)[0] == "timeline"
    assert temporal_intent("When was pgvector introduced?", today)[0] == "timeline"


def test_strip_internal_details_removes_leaked_fields_but_keeps_bracket_citations():
    from app.services.generation import strip_internal_details

    uid = "3f125a7a-39c7-43f4-846d-9d6753a67d96"
    text = f"Budget is INR 500,000 [{uid}] effective_at 2026-09-01T10:00:00+05:30\nOther {uid} fact (effective_at=2026-10-10)"
    out = strip_internal_details(text)
    assert f"[{uid}]" in out
    assert "effective_at" not in out and out.count(uid) == 1


def test_project_scope_selects_named_projects_only():
    from app.services.scope import detect_scope, distinctive_terms

    ai, atlas1, atlas2 = uuid4(), uuid4(), uuid4()
    library = [
        (ai, "Project AI Automations Operations Bot", {}),
        (atlas1, "Project Atlas - Initial Budget", {"project": "Project Atlas"}),
        (atlas2, "Project Atlas - Revised Budget", {"project": "Project Atlas"}),
    ]
    q = "What is happening recently in the AI Automations project?"
    assert distinctive_terms(q) == ["ai", "automation"]
    assert detect_scope(q, library) == {ai}
    assert detect_scope("What was the Project Atlas budget on September 15, 2026?", library) == {atlas1, atlas2}
    assert detect_scope("Compare AI Automations and Project Atlas", library) == {ai, atlas1, atlas2}
    # broad / unnamed questions stay unscoped; a lone word like "AI" is not enough to pick a project
    assert detect_scope("Tell me about all my AI projects", library) == set()
    assert detect_scope("What have I saved recently?", library) == set()
    assert detect_scope("When was pgvector introduced?", library) == set()


def test_cited_sources_keeps_only_cited_items_in_citation_order():
    from datetime import UTC, datetime

    from app.schemas.query import SourceReference
    from app.services.generation import cited_sources

    def source(title):
        return SourceReference(
            item_id=uuid4(), title=title, source_url=None, chunk_id=uuid4(), excerpt="x",
            effective_at=None, created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    a, b, c = source("A"), source("B"), source("C")
    answer = f"Fact [{b.item_id}] and more [{a.item_id}] again [{b.item_id}]. Unknown [{uuid4()}]."
    assert [s.title for s in cited_sources(answer, [a, b, c])] == ["B", "A"]
    assert cited_sources("No citations here.", [a, b, c]) == []


def test_follow_up_retrieval_uses_current_question_for_entities_not_history(monkeypatch):
    import asyncio

    from app.services.generation import QueryService

    seen = {}

    class Retrieval:
        async def retrieve(self, *_args, focus=None, **_kwargs):
            seen["focus"] = focus
            return []

    asyncio.run(
        QueryService(DummyEmbeddings(), Retrieval()).answer(
            object(), uuid4(), "and whats the budget revision for project atlas?",
            history=[{"role": "user", "content": "what do i work on with yash"}],
        )
    )
    assert seen["focus"] == "and whats the budget revision for project atlas?"


def test_attach_sources_grounds_uncited_answers_and_never_attaches_unrelated_chunks():
    from datetime import UTC, datetime

    from app.schemas.query import SourceReference
    from app.services.generation import attach_sources

    def source(title, text):
        return SourceReference(
            item_id=uuid4(), title=title, source_url=None, chunk_id=uuid4(), excerpt=text,
            effective_at=None, created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    budget = source("Budget", "The initial approved budget for Project Atlas is INR 500000. This budget covers development, hosting, testing, and initial launch expenses.")
    revised = source("Revised", "The Project Atlas budget has been revised from INR 500000 to INR 750000. The additional allocation is for expanded testing and infrastructure requirements.")
    other = source("AI Bot", "Make a plan to start automating almost everything inside company operations pipelines, with yash.")
    answer = "Budget\n- Initial approved budget: INR 500,000, covering development, hosting, testing and initial launch.\n- Revised to INR 750,000 for expanded testing and infrastructure."
    text, supporting = attach_sources(answer, [budget, revised, other])
    assert [s.title for s in supporting] == ["Budget", "Revised"]  # no uncited, unrelated chunk
    assert f"[{budget.item_id}]" in text and f"[{revised.item_id}]" in text  # markers match the list
    assert str(other.item_id) not in text

    # honest no-evidence answers get no sources; an uncited answer unrelated to every chunk gets none
    assert attach_sources("The saved knowledge does not contain sufficient information.", [budget])[1] == []
    assert attach_sources("Completely different topic about gardening and soil.", [budget, other])[1] == []

    # model-cited sources stay first; grounded extras follow
    cited = f"Initial budget was INR 500,000 [{budget.item_id}]. Revised to INR 750,000 for expanded testing and infrastructure."
    _, merged = attach_sources(cited, [revised, budget])
    assert [s.title for s in merged] == ["Budget", "Revised"]
