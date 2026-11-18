from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.common import APIModel


class Credentials(APIModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)


class UserResponse(APIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    display_name: str | None = None
    created_at: datetime


class ProfileUpdate(APIModel):
    """Only the display name is editable; unknown fields (e.g. email) are rejected."""

    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if any(not char.isprintable() for char in cleaned):
            raise ValueError("Display name contains unsupported characters")
        return cleaned or None


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
