from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.models import Chunk, Item
from app.models.item import ItemStatus, SourceType
from app.schemas.ingest import IngestRequest
from app.schemas.item import ItemUpdate
from app.schemas.query import SourceReference
from app.services.chunking import chunk_text
from app.services.generation import QueryService, keep_retrieved_citations
from app.services.ingestion import IngestionService
from app.services.items import ItemService
from app.services.url_extractor import _validate_public_url


class FakeSession:
    def __init__(self, item=None):
        self.item = item
        self.commits = 0
        self.rollbacks = 0

    def add(self, item):
        if isinstance(item, Item):
            self.item = item

    def add_all(self, objects):
        self.item.chunks.extend(objects)

    async def get(self, _model, _item_id):
        return self.item

    async def scalar(self, _statement):
        if "max(item_revisions.revision_number)" in str(_statement):
            return None
        return self.item

    async def commit(self):
        self.commits += 1

    async def execute(self, _statement):
        self.item.chunks.clear()

    async def flush(self):
        if self.item is not None and self.item.id is None:
            self.item.id = uuid4()

    async def refresh(self, _item):
        pass

    async def rollback(self):
        self.rollbacks += 1


class FakeEmbeddings:
    def embed_texts(self, texts):
        return [[float(len(text)), *([0.0] * 2047)] for text in texts]

    def embed_query(self, _query):
        return [0.0] * 2048


@pytest.mark.asyncio
async def test_note_ingestion_chunks_and_persists_embeddings():
    session = FakeSession()
    user_id = uuid4()
    item = await IngestionService(FakeEmbeddings()).ingest(
        session, IngestRequest(source_type=SourceType.note, content="A sentence. Another sentence."), user_id
    )
    assert item.status == ItemStatus.ACTIVE
    assert item.content == "A sentence. Another sentence."
    assert item.chunks
    assert len(item.chunks[0].embedding) == 2048
    assert session.commits == 2


@pytest.mark.asyncio
async def test_embedding_failure_is_recorded_on_item():
    class BrokenEmbeddings:
        def embed_texts(self, _texts):
            raise ServiceUnavailableError("model unavailable")

    session = FakeSession()
    user_id = uuid4()
    with pytest.raises(ServiceUnavailableError):
        await IngestionService(BrokenEmbeddings()).ingest(
            session, IngestRequest(source_type=SourceType.note, content="A note"), user_id
        )
    assert session.item.status == ItemStatus.FAILED
    assert session.item.error_message == "model unavailable"
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_update_replaces_existing_chunks():
    item = Item(
        title="Existing",
        content="Old content",
        source_type=SourceType.note,
        status=ItemStatus.FAILED,
        error_message="previous error",
        chunks=[Chunk(chunk_index=0, content="old chunk", embedding=[0.0] * 2048)],
    )
    session = FakeSession(item)
    service = ItemService(FakeEmbeddings())
    updated = await service.update(session, uuid4(), uuid4(), ItemUpdate(content="Replacement content."))
    assert updated.content == "Replacement content."
    assert all(chunk.content != "old chunk" for chunk in updated.chunks)
    assert updated.chunks
    assert updated.status == ItemStatus.ACTIVE
    assert updated.error_message is None


@pytest.mark.asyncio
async def test_failed_update_keeps_previous_content_and_chunks():
    item = Item(
        title="Existing",
        content="Previous durable fact",
        source_type=SourceType.note,
        status=ItemStatus.ACTIVE,
        chunks=[Chunk(chunk_index=0, content="Previous durable fact", embedding=[0.0] * 2048)],
    )

    class BrokenEmbeddings:
        def embed_texts(self, _texts):
            raise RuntimeError("embedding failure")

    session = FakeSession(item)
    with pytest.raises(RuntimeError, match="embedding failure"):
        await ItemService(BrokenEmbeddings()).update(
            session,
            uuid4(),
            uuid4(),
            ItemUpdate(title="Would be new", content="Replacement fact"),
        )
    assert item.title == "Existing"
    assert item.content == "Previous durable fact"
    assert item.chunks[0].content == "Previous durable fact"
    assert item.status == ItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_url_content_is_extracted_in_server_service(monkeypatch):
    from app.services import ingestion

    async def fake_extract(_url):
        return "Extracted title", "Extracted page content."

    monkeypatch.setattr(ingestion, "extract_url", fake_extract)
    session = FakeSession()
    item = await IngestionService(FakeEmbeddings()).ingest(
        session,
        IngestRequest(source_type=SourceType.url, source_url="https://example.com/page"),
        uuid4(),
    )
    assert item.title == "Extracted title"
    assert item.content == "Extracted page content."
    assert item.status == ItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_url_extraction_failure_is_recorded(monkeypatch):
    from app.core.exceptions import AppError
    from app.services import ingestion

    async def broken_extract(_url):
        raise AppError("fetch failed")

    monkeypatch.setattr(ingestion, "extract_url", broken_extract)
    session = FakeSession()
    with pytest.raises(AppError, match="fetch failed"):
        await IngestionService(FakeEmbeddings()).ingest(
            session,
            IngestRequest(source_type=SourceType.url, source_url="https://example.com/page"),
            uuid4(),
        )
    assert session.item.status == ItemStatus.FAILED
    assert session.item.error_message == "fetch failed"


def test_citations_are_restricted_to_retrieved_item_ids():
    source_id = uuid4()
    source = SourceReference(
        item_id=source_id,
        title="Source",
        source_url=None,
        chunk_id=uuid4(),
        excerpt="Text",
        effective_at=None,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    answer = keep_retrieved_citations("Claim [1], false claim [2], unknown [not-a-source].", [source])
    assert f"[{source_id}]" in answer
    assert "[2]" not in answer
    assert "[not-a-source]" not in answer


def test_vector_column_dimension_matches_configured_initial_model():
    assert Chunk.__table__.c.embedding.type.dim == 2048


def test_chunker_does_not_drop_overlong_words():
    text = "x" * 37
    chunks = chunk_text(text, chunk_size=10, overlap=2)
    assert all(len(chunk) <= 10 for chunk in chunks)
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_openrouter_needs_credentials_only_when_generating(monkeypatch):
    from app.providers import openrouter

    monkeypatch.setattr(
        openrouter, "get_settings", lambda: Settings(openrouter_api_key=None, openrouter_chat_model=None)
    )
    provider = openrouter.OpenRouterProvider()
    with pytest.raises(ServiceUnavailableError, match="OPENROUTER_API_KEY"):
        await provider.generate(question="Question", context="")


@pytest.mark.asyncio
async def test_url_extractor_rejects_private_network_addresses():
    from app.core.exceptions import InvalidSourceError

    for url in ("http://127.0.0.1/admin", "http://[::1]/admin"):
        with pytest.raises(InvalidSourceError):
            await _validate_public_url(url)


@pytest.mark.asyncio
async def test_query_service_returns_no_context_answer_without_calling_llm():
    class EmptyRetrieval:
        async def retrieve(self, *_args, **_kwargs):
            return []

    response = await QueryService(FakeEmbeddings(), EmptyRetrieval()).answer(
        FakeSession(), uuid4(), "Unknown"
    )
    assert response.sources == []
    assert "couldn't find relevant" in response.answer


@pytest.mark.asyncio
async def test_query_service_mocks_provider_and_rewrites_only_retrieved_citations(monkeypatch):
    from app.services import generation

    item_id = uuid4()
    chunk = Chunk(id=uuid4(), item_id=item_id, chunk_index=0, content="Relevant fact", embedding=[0.0] * 2048)
    item = Item(
        id=item_id,
        title="Source title",
        content="Relevant fact",
        source_type=SourceType.note,
        status=ItemStatus.ACTIVE,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )

    class OneResult:
        async def retrieve(self, *_args, **_kwargs):
            return [(chunk, item, 0.8)]

    class MockProvider:
        async def generate(self, *, question, context, history=None):
            assert question == "What is the fact?"
            assert f"item_id={item_id}" in context
            return "The fact is relevant [1], fabricated [2]."

    monkeypatch.setattr(generation, "get_llm_provider", lambda: MockProvider())
    response = await QueryService(FakeEmbeddings(), OneResult()).answer(
        FakeSession(), uuid4(), "What is the fact?"
    )
    assert f"[{item_id}]" in response.answer
    assert "[2]" not in response.answer
    assert response.sources[0].item_id == item_id
