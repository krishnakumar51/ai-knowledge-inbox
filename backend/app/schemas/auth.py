from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.common import APIModel


class Credentials(APIModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)


class UserResponse(APIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    created_at: datetime


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
