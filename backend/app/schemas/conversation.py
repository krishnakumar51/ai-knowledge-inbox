from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.common import APIModel


class ConversationCreate(APIModel):
    title: str = Field(default="New conversation", min_length=1, max_length=300)


class ConversationRename(APIModel):
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned or any(not char.isprintable() for char in cleaned):
            raise ValueError("Title must contain printable text")
        return cleaned


class MessageCreate(APIModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageResponse(APIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    content: str
    citations: list[dict] | None
    created_at: datetime


class ConversationResponse(APIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]


class ChatResponse(APIModel):
    conversation_id: UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
