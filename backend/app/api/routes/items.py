from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import current_user
from app.core.exceptions import AppError
from app.db.session import get_db
from app.models import User
from app.schemas.item import ItemList, ItemResponse, ItemUpdate
from app.schemas.revision import ItemRevisionResponse
from app.services.items import ItemService

router = APIRouter()


def _item_error_status(exc: AppError) -> int:
    if exc.message in {"Item not found", "Revision not found"}:
        return 404
    if exc.status_code != 500:
        return exc.status_code
    return 422


@router.get("/items/{item_id}/history", response_model=list[ItemRevisionResponse])
async def item_history(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    try:
        return await ItemService().history(db, user.id, item_id)
    except AppError as exc:
        raise HTTPException(404, exc.message) from exc


@router.get("/items/{item_id}/history/{revision_id}", response_model=ItemRevisionResponse)
async def item_revision(
    item_id: UUID,
    revision_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        return await ItemService().get_revision(db, user.id, item_id, revision_id)
    except AppError as exc:
        raise HTTPException(404, exc.message) from exc


@router.post("/items/{item_id}/restore/{revision_id}", response_model=ItemResponse)
async def restore_item_revision(
    item_id: UUID,
    revision_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        return await ItemService().restore(db, user.id, item_id, revision_id)
    except AppError as exc:
        raise HTTPException(_item_error_status(exc), exc.message) from exc


@router.get("/items", response_model=ItemList)
async def list_items(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    items, total = await ItemService().list(db, user.id, offset, limit)
    return ItemList(items=items, total=total)


@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    try:
        return await ItemService().get(db, user.id, item_id)
    except AppError as exc:
        raise HTTPException(404, exc.message) from exc


@router.patch("/items/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: UUID, payload: ItemUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
):
    try:
        return await ItemService().update(db, user.id, item_id, payload)
    except AppError as exc:
        raise HTTPException(_item_error_status(exc), exc.message) from exc


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    try:
        await ItemService().delete(db, user.id, item_id)
    except AppError as exc:
        raise HTTPException(404, exc.message) from exc
