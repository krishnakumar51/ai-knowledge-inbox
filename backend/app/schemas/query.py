from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class QueryRequest(APIModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceReference(APIModel):
    item_id: UUID
    title: str
    source_url: str | None
    chunk_id: UUID
    excerpt: str
    effective_at: datetime | None
    created_at: datetime


class QueryResponse(APIModel):
    answer: str
    sources: list[SourceReference]
