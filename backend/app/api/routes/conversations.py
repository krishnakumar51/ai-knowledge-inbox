from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import current_user
from app.db.session import get_db
from app.models import Conversation, Item, Message, MessageRole, User
from app.models.item import ItemStatus
from app.schemas.conversation import (
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    ConversationResponse,
    MessageCreate,
)
from app.services.generation import QueryService
from app.services.titles import DEFAULT_TITLE, generate_title

router = APIRouter(prefix="/conversations")


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
):
    conversation = Conversation(user_id=user.id, title=payload.title.strip())
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    return list(
        (
            await db.scalars(
                select(Conversation)
                .where(Conversation.user_id == user.id)
                .order_by(Conversation.updated_at.desc())
            )
        ).all()
    )


async def _owned_conversation(db: AsyncSession, user_id, conversation_id: UUID, with_messages: bool = False):
    statement = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    if with_messages:
        statement = statement.options(selectinload(Conversation.messages))
    return await db.scalar(statement)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
):
    conversation = await _owned_conversation(db, user.id, conversation_id, with_messages=True)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    return conversation


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: UUID,
    payload: ConversationRename,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    conversation = await _owned_conversation(db, user.id, conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    conversation.title = payload.title
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
):
    conversation = await _owned_conversation(db, user.id, conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    await db.delete(conversation)
    await db.commit()


@router.post("/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    conversation = await _owned_conversation(db, user.id, conversation_id, with_messages=True)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    prior = [
        {"role": message.role.value, "content": message.content} for message in conversation.messages[-10:]
    ]
    user_message = Message(
        conversation_id=conversation.id, role=MessageRole.user, content=payload.content.strip()
    )
    db.add(user_message)
    await db.flush()
    conversation.updated_at = datetime.now(UTC)
    if conversation.title == DEFAULT_TITLE:
        # Generated once from the first question; renamed or already-titled conversations are left alone.
        candidates = (
            await db.execute(
                select(Item.id, Item.title, Item.source_metadata).where(
                    Item.user_id == user.id, Item.status == ItemStatus.ACTIVE
                )
            )
        ).all()
        conversation.title = generate_title(payload.content, [(r[0], r[1], r[2]) for r in candidates])
    # Keep the submitted question even if embeddings or chat generation fail.
    # The assistant response is committed separately only after generation succeeds.
    await db.commit()
    await db.refresh(user_message)
    try:
        response = await QueryService().answer(db, user.id, payload.content.strip(), history=prior)
        assistant_message = Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=response.answer,
            citations=[source.model_dump(mode="json") for source in response.sources],
        )
        db.add(assistant_message)
        conversation.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(user_message)
        await db.refresh(assistant_message)
        await db.refresh(conversation)
        return ChatResponse(
            conversation_id=conversation.id, user_message=user_message, assistant_message=assistant_message
        )
    except Exception:
        await db.rollback()
        raise
