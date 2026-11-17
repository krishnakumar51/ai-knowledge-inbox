from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Chunk, Item
from app.models.item import ItemStatus


class RetrievalService:
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
    ):
        vector_distance = Chunk.embedding.cosine_distance(query_vector)
        approximate_distance = Chunk.embedding.cast(HALFVEC(get_settings().embedding_dimensions)).cosine_distance(
            query_vector
        )
        candidate_count = max(top_k * 4, top_k)
        filters = [Item.status == ItemStatus.ACTIVE, Item.user_id == user_id]
        applicable_at = func.coalesce(Item.effective_at, Item.created_at)
        if effective_before is not None:
            filters.append(applicable_at <= effective_before)
        if effective_after is not None:
            filters.append(applicable_at > effective_after)
        vector_stmt = (
            select(Chunk, Item, (1 - vector_distance).label("score"))
            .join(Item)
            .where(*filters)
            .order_by(approximate_distance)
            .limit(candidate_count)
        )
        keyword_stmt = (
            select(
                Chunk,
                Item,
                func.ts_rank_cd(
                    func.to_tsvector("english", Chunk.content), func.plainto_tsquery("english", question)
                ).label("score"),
            )
            .join(Item)
            .where(
                *filters,
                func.to_tsvector("english", Chunk.content).op("@@")(
                    func.plainto_tsquery("english", question)
                ),
            )
            .order_by(text("score DESC"))
            .limit(candidate_count)
        )
        vector_rows, keyword_rows = (
            (await db.execute(vector_stmt)).all(),
            (await db.execute(keyword_stmt)).all(),
        )
        combined = {}
        for rows in (vector_rows, keyword_rows):
            for chunk, item, score in rows:
                key = chunk.id
                previous = combined.get(key)
                combined[key] = (chunk, item, max(float(score), previous[2] if previous else 0.0))
        ranked = sorted(combined.values(), key=lambda row: row[2], reverse=True)
        return ranked[:top_k]
