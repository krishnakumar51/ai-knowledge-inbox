import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.user import User


class SourceType(str, enum.Enum):
    note = "note"
    url = "url"


class ItemStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


def _enum_values(enum_class):
    return [member.value for member in enum_class]


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("user_id", "dataset_id", "external_id", name="uq_items_dataset_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False, index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    dataset_id: Mapped[str | None] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(250))
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus, name="item_status", values_callable=_enum_values),
        nullable=False,
        default=ItemStatus.PROCESSING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )
    user: Mapped["User"] = relationship(back_populates="items")


class RevisionChangeType(str, enum.Enum):
    CREATED = "CREATED"
    CONTENT_UPDATED = "CONTENT_UPDATED"
    METADATA_UPDATED = "METADATA_UPDATED"
    URL_UPDATED = "URL_UPDATED"
    RESTORED = "RESTORED"


class ItemRevision(Base):
    __tablename__ = "item_revisions"
    __table_args__ = (UniqueConstraint("item_id", "revision_number", name="uq_item_revisions_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    source_type_snapshot: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    source_url_snapshot: Mapped[str | None] = mapped_column(Text)
    source_metadata_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    effective_at_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_snapshot: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus, name="item_status", values_callable=_enum_values), nullable=False
    )
    change_type: Mapped[RevisionChangeType] = mapped_column(
        Enum(RevisionChangeType, name="revision_change_type"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    change_summary: Mapped[str | None] = mapped_column(Text)
