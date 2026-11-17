from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import Chunk, Item, ItemRevision
from app.models.item import ItemStatus, RevisionChangeType
from app.schemas.item import ItemUpdate
from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingService
from app.services.url_extractor import extract_url


class ItemService:
    def __init__(self, embeddings: EmbeddingService | None = None):
        self.embeddings = embeddings or EmbeddingService()

    async def list(self, db: AsyncSession, user_id: UUID, offset: int, limit: int):
        scope = Item.user_id == user_id
        total = await db.scalar(select(func.count()).select_from(Item).where(scope))
        items = (
            await db.scalars(
                select(Item).where(scope).order_by(Item.created_at.desc()).offset(offset).limit(limit)
            )
        ).all()
        return list(items), total or 0

    async def get(self, db: AsyncSession, user_id: UUID, item_id: UUID, *, for_update: bool = False) -> Item:
        statement = select(Item).where(Item.id == item_id, Item.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        item = await db.scalar(statement)
        if item is None:
            raise AppError("Item not found")
        return item

    async def update(self, db: AsyncSession, user_id: UUID, item_id: UUID, payload: ItemUpdate) -> Item:
        item = await self.get(db, user_id, item_id, for_update=True)
        changes = payload.model_dump(exclude_unset=True)
        new_chunks = None
        source_url = str(changes["source_url"]) if changes.get("source_url") else None
        url_changed = "source_url" in changes and source_url != item.source_url
        content_changed = changes.get("content") is not None and changes["content"].strip() != item.content
        title = changes.get("title")
        if url_changed:
            if item.source_type.value != "url" or source_url is None:
                raise AppError("Only URL items can change to another URL")
            extracted_title, extracted_content = await extract_url(source_url)
            if title is None:
                title = extracted_title
            content_changed = extracted_content.strip() != item.content
            changes["content"] = extracted_content
        if content_changed:
            content = changes["content"].strip()
            if not content:
                raise AppError("Content cannot be empty")
            parts = chunk_text(
                content, chunk_size=get_settings().chunk_size, overlap=get_settings().chunk_overlap
            )
            vectors = await asyncio.to_thread(self.embeddings.embed_texts, parts)
            new_chunks = (content, parts, vectors)
        if title is not None:
            item.title = title
        if "effective_at" in changes:
            item.effective_at = changes["effective_at"]
        if url_changed:
            item.source_url = source_url
        if "source_metadata" in changes:
            item.source_metadata = changes["source_metadata"] or {}
        if new_chunks is not None:
            content, parts, vectors = new_chunks
            item.content = content
            item.error_message = None
            await db.execute(delete(Chunk).where(Chunk.item_id == item.id))
            await db.flush()
            db.add_all(
                Chunk(item_id=item.id, chunk_index=i, content=part, embedding=vector)
                for i, (part, vector) in enumerate(zip(parts, vectors, strict=True))
            )
            item.status = ItemStatus.ARCHIVED if item.status == ItemStatus.ARCHIVED else ItemStatus.ACTIVE
        requested_status = changes.get("status")
        if requested_status is not None:
            if requested_status == ItemStatus.ACTIVE:
                chunk_count = await db.scalar(
                    select(func.count()).select_from(Chunk).where(Chunk.item_id == item.id)
                )
                if not chunk_count:
                    raise AppError("An item must have processed chunks before it can be activated")
            item.status = requested_status
        if changes:
            revision_type = (
                RevisionChangeType.URL_UPDATED
                if url_changed
                else RevisionChangeType.CONTENT_UPDATED
                if content_changed
                else RevisionChangeType.METADATA_UPDATED
            )
            await self._add_revision(db, item, revision_type)
        await db.commit()
        await db.refresh(item)
        return item

    async def delete(self, db: AsyncSession, user_id: UUID, item_id: UUID) -> None:
        item = await self.get(db, user_id, item_id)
        await db.delete(item)
        await db.commit()

    async def _add_revision(
        self,
        db: AsyncSession,
        item: Item,
        change_type: RevisionChangeType,
        change_summary: str | None = None,
    ) -> ItemRevision:
        current = await db.scalar(
            select(func.max(ItemRevision.revision_number)).where(ItemRevision.item_id == item.id)
        )
        revision = ItemRevision(
            item_id=item.id,
            user_id=item.user_id,
            revision_number=(current or 0) + 1,
            title_snapshot=item.title,
            content_snapshot=item.content,
            source_type_snapshot=item.source_type,
            source_url_snapshot=item.source_url,
            source_metadata_snapshot=item.source_metadata or {},
            effective_at_snapshot=item.effective_at,
            status_snapshot=item.status,
            change_type=change_type,
            change_summary=change_summary,
        )
        db.add(revision)
        return revision

    async def history(self, db: AsyncSession, user_id: UUID, item_id: UUID) -> list[ItemRevision]:
        await self.get(db, user_id, item_id)
        return list(
            (
                await db.scalars(
                    select(ItemRevision)
                    .where(ItemRevision.item_id == item_id, ItemRevision.user_id == user_id)
                    .order_by(ItemRevision.revision_number.desc())
                )
            ).all()
        )

    async def get_revision(
        self, db: AsyncSession, user_id: UUID, item_id: UUID, revision_id: UUID
    ) -> ItemRevision:
        await self.get(db, user_id, item_id)
        revision = await db.scalar(
            select(ItemRevision).where(
                ItemRevision.id == revision_id,
                ItemRevision.item_id == item_id,
                ItemRevision.user_id == user_id,
            )
        )
        if revision is None:
            raise AppError("Revision not found")
        return revision

    async def restore(self, db: AsyncSession, user_id: UUID, item_id: UUID, revision_id: UUID) -> Item:
        item = await self.get(db, user_id, item_id, for_update=True)
        revision = await self.get_revision(db, user_id, item_id, revision_id)
        new_chunks = None
        if item.content != revision.content_snapshot:
            parts = chunk_text(
                revision.content_snapshot,
                chunk_size=get_settings().chunk_size,
                overlap=get_settings().chunk_overlap,
            )
            vectors = await asyncio.to_thread(self.embeddings.embed_texts, parts)
            new_chunks = (parts, vectors)
        item.title = revision.title_snapshot
        item.source_type = revision.source_type_snapshot
        item.source_url = revision.source_url_snapshot
        item.source_metadata = revision.source_metadata_snapshot or {}
        item.effective_at = revision.effective_at_snapshot
        item.content = revision.content_snapshot
        item.error_message = None
        if new_chunks is not None:
            parts, vectors = new_chunks
            await db.execute(delete(Chunk).where(Chunk.item_id == item.id))
            await db.flush()
            db.add_all(
                Chunk(item_id=item.id, chunk_index=index, content=part, embedding=vector)
                for index, (part, vector) in enumerate(zip(parts, vectors, strict=True))
            )
        item.status = (
            ItemStatus.ARCHIVED if revision.status_snapshot == ItemStatus.ARCHIVED else ItemStatus.ACTIVE
        )
        await self._add_revision(
            db, item, RevisionChangeType.RESTORED, f"Restored revision {revision.revision_number}"
        )
        await db.commit()
        await db.refresh(item)
        return item
