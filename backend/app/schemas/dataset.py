from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import parse_import_timestamp
from app.models.item import SourceType


class HistoricalDatasetItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str = Field(min_length=1, max_length=250)
    source_type: SourceType
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=1)
    source_url: AnyHttpUrl | None = Field(
        default=None, validation_alias=AliasChoices("source_url", "url")
    )
    created_at: datetime
    effective_at: datetime | None = None
    source_metadata: dict = Field(
        default_factory=dict, validation_alias=AliasChoices("source_metadata", "metadata")
    )
    status: Literal["ACTIVE"] = "ACTIVE"

    @field_validator("created_at", "effective_at", mode="before")
    @classmethod
    def parse_historical_dates(cls, value):
        return None if value is None else parse_import_timestamp(value, naive_is_local=True)

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_type == SourceType.note and not self.content:
            raise ValueError("content is required for notes")
        if self.source_type == SourceType.url and not self.source_url:
            raise ValueError("source_url is required for URLs")
        if self.source_type == SourceType.note and self.source_url:
            raise ValueError("source_url is only valid for URL items")
        return self


class HistoricalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=200)
    dataset_name: str | None = Field(default=None, max_length=200)
    user_email: str = Field(min_length=3, max_length=320)
    items: list[HistoricalDatasetItem] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_external_ids(self):
        ids = [item.external_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("external_id values must be unique within the dataset")
        return self
