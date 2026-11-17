from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict

from app.models.item import ItemStatus, RevisionChangeType, SourceType
from app.schemas.common import APIModel


class ItemRevisionResponse(APIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    revision_number: int
    title_snapshot: str
    content_snapshot: str
    source_type_snapshot: SourceType
    source_url_snapshot: str | None
    source_metadata_snapshot: dict
    effective_at_snapshot: datetime | None
    status_snapshot: ItemStatus
    change_type: RevisionChangeType
    changed_at: datetime
    change_summary: str | None
