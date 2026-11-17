from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, AnyHttpUrl, ConfigDict, Field, field_validator

from app.core.time import as_utc
from app.models.item import ItemStatus, SourceType
from app.schemas.common import APIModel


class ItemResponse(APIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    content: str
    source_type: SourceType
    source_url: str | None
    source_metadata: dict
    external_id: str | None = None
    status: ItemStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    effective_at: datetime | None


class ItemList(APIModel):
    items: list[ItemResponse]
    total: int


class ItemUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1)
    effective_at: datetime | None = None
    source_url: AnyHttpUrl | None = None
    source_metadata: dict | None = Field(
        default=None, validation_alias=AliasChoices("source_metadata", "metadata")
    )
    status: ItemStatus | None = None

    @field_validator("effective_at")
    @classmethod
    def require_timezone_on_effective_at(cls, value):
        if value is not None:
            as_utc(value)
        return value

    @field_validator("status")
    @classmethod
    def only_archive_transitions(cls, value):
        if value not in {None, ItemStatus.ACTIVE, ItemStatus.ARCHIVED}:
            raise ValueError("Items can only be activated or archived through this endpoint")
        return value


class IngestResponse(APIModel):
    id: UUID
    title: str
    status: ItemStatus
    chunk_count: int
