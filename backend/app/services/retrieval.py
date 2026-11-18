import re
from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Chunk, Item
from app.models.item import ItemStatus
from app.services.scope import detect_scope, distinctive_terms, or_tsquery, project_key

RRF_K = 60  # standard Reciprocal Rank Fusion constant
MAX_CHUNKS_PER_ITEM = 3


def _normalized(text_value: str) -> str:
    return re.sub(r"\s+", " ", text_value).strip().lower()


class RetrievalService:
    """Hybrid retrieval over one user's ACTIVE items.

    1. Named-project scope: if the question names a project/entity (see ``services.scope``), the
       vector search is restricted to that project's items. Chunks from other items are admitted only
       if they contain one of the question's distinctive words (keyword branch).
    2. Vector branch: cosine similarity over pgvector (ANN through a halfvec cast).
    3. Keyword branch: PostgreSQL full-text search with an OR query of the distinctive terms.
    4. The two ranked lists are fused with Reciprocal Rank Fusion (rank based, so the incompatible
       score scales of cosine similarity and ts_rank never get mixed). Each chunk keeps its cosine
       similarity as its relevance score for thresholding.
    5. Relevance gate: keep keyword hits, plus vector hits within a margin of the best similarity and
       above the configured minimum. Then drop duplicate text and cap chunks per item.
    """

    async def retrieve(
        self,
        db: AsyncSession,
        user_id: UUID,
        query_vector: list[float],
        question: str,
        top_k: int,
        *,
        effective_before: datetime | None = None,
        effective_after: datetime | None = None,
        focus: str | None = None,
    ):
        settings = get_settings()
        filters = [Item.status == ItemStatus.ACTIVE, Item.user_id == user_id]
        applicable_at = func.coalesce(Item.effective_at, Item.created_at)
        if effective_before is not None:
            filters.append(applicable_at <= effective_before)
        if effective_after is not None:
            filters.append(applicable_at > effective_after)

        # Entities/keywords come from the current question; earlier turns only shape the embedding.
        focus = focus or question
        terms = distinctive_terms(focus)
        scope: set[UUID] = set()
        key_of: dict[UUID, str] = {}
        if terms:
            candidates = (
                await db.execute(
                    select(Item.id, Item.title, Item.source_metadata).where(
                        Item.status == ItemStatus.ACTIVE, Item.user_id == user_id
                    )
                )
            ).all()
            scope = detect_scope(focus, [(row[0], row[1], row[2]) for row in candidates])
            key_of = {row[0]: project_key(row[1], row[2]) for row in candidates if row[0] in scope}

        vector_distance = Chunk.embedding.cosine_distance(query_vector)
        approximate_distance = Chunk.embedding.cast(HALFVEC(settings.embedding_dimensions)).cosine_distance(
            query_vector
        )
        candidate_count = max(top_k * 4, top_k)
        vector_filters = [*filters, Item.id.in_(scope)] if scope else filters
        vector_stmt = (
            select(Chunk, Item, (1 - vector_distance).label("score"))
            .join(Item)
            .where(*vector_filters)
            .order_by(approximate_distance)
            .limit(candidate_count)
        )
        vector_rows = (await db.execute(vector_stmt)).all()

        keyword_rows = []
        tsquery_text = or_tsquery(terms)
        if tsquery_text:
            tsquery = func.to_tsquery("english", tsquery_text)
            vector_column = func.to_tsvector("english", Chunk.content)
            keyword_stmt = (
                select(
                    Chunk,
                    Item,
                    (1 - vector_distance).label("score"),
                    func.ts_rank_cd(vector_column, tsquery).label("keyword_score"),
                )
                .join(Item)
                .where(*filters, vector_column.op("@@")(tsquery))
                .order_by(text("keyword_score DESC"))
                .limit(candidate_count)
            )
            keyword_rows = (await db.execute(keyword_stmt)).all()

        fused: dict[UUID, dict] = {}
        for rank, (chunk, item, score) in enumerate(vector_rows, 1):
            entry = fused.setdefault(chunk.id, {"chunk": chunk, "item": item, "sim": float(score), "rrf": 0.0, "kw": False})
            entry["rrf"] += 1 / (RRF_K + rank)
        for rank, (chunk, item, score, _keyword_score) in enumerate(keyword_rows, 1):
            entry = fused.setdefault(chunk.id, {"chunk": chunk, "item": item, "sim": float(score), "rrf": 0.0, "kw": False})
            entry["rrf"] += 1 / (RRF_K + rank)
            entry["kw"] = True
        if not fused:
            return []

        ranked = sorted(fused.values(), key=lambda entry: entry["rrf"], reverse=True)
        best_similarity = max(entry["sim"] for entry in ranked)
        floor = max(settings.retrieval_min_score, best_similarity - settings.retrieval_relevance_margin)
        selected, seen_text, per_item, guaranteed = [], set(), {}, set()
        for entry in ranked:
            if not entry["kw"] and entry["sim"] < floor:
                # A comparison names several projects: always keep each named project's best chunk.
                key = key_of.get(entry["item"].id)
                if key is None or key in guaranteed:
                    continue
            if (key := key_of.get(entry["item"].id)) is not None:
                guaranteed.add(key)
            fingerprint = _normalized(entry["chunk"].content)
            item_id = entry["item"].id
            if fingerprint in seen_text or per_item.get(item_id, 0) >= MAX_CHUNKS_PER_ITEM:
                continue
            seen_text.add(fingerprint)
            per_item[item_id] = per_item.get(item_id, 0) + 1
            selected.append((entry["chunk"], entry["item"], entry["sim"]))
            if len(selected) == top_k:
                break
        return selected
