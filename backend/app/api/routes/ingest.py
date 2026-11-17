from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import current_user
from app.db.session import get_db
from app.models import Chunk, User
from app.schemas.ingest import IngestRequest
from app.schemas.item import IngestResponse
from app.services.ingestion import IngestionService

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest(
    payload: IngestRequest, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
):
    item = await IngestionService().ingest(db, payload, user.id)
    chunk_count = await db.scalar(select(func.count()).select_from(Chunk).where(Chunk.item_id == item.id))
    return IngestResponse(id=item.id, title=item.title, status=item.status, chunk_count=chunk_count or 0)
