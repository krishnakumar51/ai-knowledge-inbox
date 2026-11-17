from datetime import datetime

from pydantic import AliasChoices, AnyHttpUrl, Field, field_validator, model_validator

from app.core.time import as_utc
from app.models.item import SourceType
from app.schemas.common import APIModel


class IngestRequest(APIModel):
    source_type: SourceType
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=1)
    source_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias=AliasChoices("source_url", "url"),
    )
    effective_at: datetime | None = None
    source_metadata: dict = Field(
        default_factory=dict, validation_alias=AliasChoices("source_metadata", "metadata")
    )

    @field_validator("effective_at")
    @classmethod
    def require_timezone_on_effective_at(cls, value):
        if value is not None:
            as_utc(value)
        return value

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_type == SourceType.note and not self.content:
            raise ValueError("content is required for notes")
        if self.source_type == SourceType.url and not self.source_url:
            raise ValueError("source_url is required for URLs")
        if self.source_type == SourceType.note and self.source_url is not None:
            raise ValueError("source_url is only valid for URL items")
        return self
