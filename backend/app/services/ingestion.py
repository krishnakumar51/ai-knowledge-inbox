import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import Chunk, Item, ItemRevision
from app.models.item import ItemStatus, RevisionChangeType, SourceType
from app.schemas.ingest import IngestRequest
from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingService
from app.services.url_extractor import extract_url

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, embeddings: EmbeddingService | None = None):
        self.embeddings = embeddings or EmbeddingService()

    async def ingest(
        self,
        db: AsyncSession,
        payload: IngestRequest,
        user_id: UUID,
        *,
        imported_created_at: datetime | None = None,
        dataset_id: str | None = None,
        external_id: str | None = None,
    ) -> Item:
        if (dataset_id is None) != (external_id is None):
            raise AppError("dataset_id and external_id must be supplied together")
        if dataset_id and external_id:
            duplicate = await db.scalar(
                select(Item.id).where(
                    Item.user_id == user_id,
                    Item.dataset_id == dataset_id,
                    Item.external_id == external_id,
                )
            )
            if duplicate:
                raise AppError(f"Dataset record already imported: {external_id}")
        content, title, source_url = (
            payload.content,
            payload.title,
            str(payload.source_url) if payload.source_url else None,
        )
        item = Item(
            title=title or (source_url or "Untitled note"),
            user_id=user_id,
            effective_at=payload.effective_at,
            created_at=imported_created_at,
            source_metadata=payload.source_metadata,
            dataset_id=dataset_id,
            external_id=external_id,
            content=(content or "").strip(),
            source_type=payload.source_type,
            source_url=source_url,
            status=ItemStatus.PROCESSING,
        )
        db.add(item)
        await db.flush()
        db.add(
            ItemRevision(
                item_id=item.id,
                user_id=user_id,
                revision_number=1,
                title_snapshot=item.title,
                content_snapshot=item.content,
                source_type_snapshot=item.source_type,
                source_url_snapshot=item.source_url,
                source_metadata_snapshot=item.source_metadata,
                effective_at_snapshot=item.effective_at,
                status_snapshot=ItemStatus.PROCESSING,
                change_type=RevisionChangeType.CREATED,
                change_summary="Initial item record",
            )
        )
        await db.commit()
        await db.refresh(item)
        try:
            if payload.source_type == SourceType.url:
                extracted_title, content = await extract_url(source_url or "")
                item.title = title or extracted_title
            content = (content or "").strip()
            if not content:
                raise AppError("Content is empty after normalization")
            item.content = content
            parts = chunk_text(
                content, chunk_size=get_settings().chunk_size, overlap=get_settings().chunk_overlap
            )
            vectors = await asyncio.to_thread(self.embeddings.embed_texts, parts)
            db.add_all(
                Chunk(item_id=item.id, chunk_index=i, content=part, embedding=vector)
                for i, (part, vector) in enumerate(zip(parts, vectors, strict=True))
            )
            item.status = ItemStatus.ACTIVE
            await db.commit()
            await db.refresh(item)
            return item
        except Exception as exc:
            item_id = item.id
            await db.rollback()
            failed_item = await db.get(Item, item_id)
            if failed_item is not None:
                failed_item.status = ItemStatus.FAILED
                failed_item.error_message = (
                    exc.message if isinstance(exc, AppError) else "Ingestion processing failed"
                )
                await db.commit()
            if isinstance(exc, AppError):
                raise
            logger.exception("Ingestion failed")
            raise AppError("Knowledge item could not be ingested") from exc
