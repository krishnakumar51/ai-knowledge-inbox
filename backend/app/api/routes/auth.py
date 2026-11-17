import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import current_user
from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.core.security import create_access_token, hash_password, require_auth_configuration, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import Credentials, TokenResponse, UserResponse

router = APIRouter(prefix="/auth")


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    return normalized


def _token(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id), expires_in=get_settings().jwt_expire_minutes * 60
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: Credentials, db: AsyncSession = Depends(get_db)):
    try:
        require_auth_configuration()
        user = User(email=normalize_email(payload.email), password_hash=hash_password(payload.password))
    except ServiceUnavailableError as exc:
        raise HTTPException(503, exc.message) from exc
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    await db.refresh(user)
    try:
        return _token(user)
    except ServiceUnavailableError as exc:
        raise HTTPException(503, exc.message) from exc


@router.post("/login", response_model=TokenResponse)
async def login(payload: Credentials, db: AsyncSession = Depends(get_db)):
    email = normalize_email(payload.email)
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    try:
        return _token(user)
    except ServiceUnavailableError as exc:
        raise HTTPException(503, exc.message) from exc


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(current_user)):
    return user
