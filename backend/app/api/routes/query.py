from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import current_user
from app.db.session import get_db
from app.models import User
from app.schemas.query import QueryRequest, QueryResponse
from app.services.generation import QueryService

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
):
    return await QueryService().answer(db, user.id, payload.question, payload.top_k)
