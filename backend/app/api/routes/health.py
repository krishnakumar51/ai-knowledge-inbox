import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import current_user
from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.db.session import get_engine
from app.models import User
from app.providers.factory import get_llm_provider

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health/db")
async def database_readiness():
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            version = await connection.scalar(text("SELECT version()"))
            vector_extension = await connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
            items_table = await connection.scalar(text("SELECT to_regclass('public.items') IS NOT NULL"))
            chunks_table = await connection.scalar(text("SELECT to_regclass('public.chunks') IS NOT NULL"))
            vector_type = await connection.scalar(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = to_regclass('public.chunks') AND attname = 'embedding' "
                    "AND NOT attisdropped"
                )
            )
            cascade_fk = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                    "WHERE conrelid = to_regclass('public.chunks') "
                    "AND confrelid = to_regclass('public.items') "
                    "AND contype = 'f' AND confdeltype = 'c')"
                )
            )
            revision_table = await connection.scalar(
                text("SELECT to_regclass('public.item_revisions') IS NOT NULL")
            )
        checks = {
            "connectivity": True,
            "pgvector_extension": bool(vector_extension),
            "items_table": bool(items_table),
            "chunks_table": bool(chunks_table),
            f"embedding_dimension_{get_settings().embedding_dimensions}": (
                str(vector_type).lower() == f"vector({get_settings().embedding_dimensions})"
            ),
            "item_chunk_cascade": bool(cascade_fk),
            "item_revision_table": bool(revision_table),
        }
        failures = [name for name, passed in checks.items() if not passed]
        if failures:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "message": "PostgreSQL is reachable, but the pgvector schema is incomplete; run Alembic migrations.",
                    "checks": checks,
                    "failed_checks": failures,
                    "database_version": version,
                },
            )
        return {"status": "ok", "database_version": version, "checks": checks}
    except ServiceUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "message": exc.message, "checks": {"connectivity": False}},
        )
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning("Database readiness check failed (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "message": "Could not connect to PostgreSQL; check DATABASE_URL, network access, credentials, and server status.",
                "checks": {"connectivity": False},
            },
        )


@router.get("/health/ai")
async def ai_readiness():
    settings = get_settings()
    key_present = bool(settings.openrouter_api_key)
    return {
        "provider": "openrouter",
        "configuration_present": key_present,
        "chat_model_configured": bool(settings.openrouter_chat_model),
        "embedding_model_configured": bool(settings.openrouter_embedding_model),
        "provider_connectivity": "not_tested",
        "chat_generation_test": "not_tested",
        "chat_model": settings.openrouter_chat_model,
        "embedding_model": settings.openrouter_embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
    }


@router.post("/health/ai/test")
async def test_chat_generation(user: User = Depends(current_user)):
    """Explicitly send a small authenticated chat request to the configured model."""
    answer = await get_llm_provider().generate(
        question="Repeat the exact diagnostic phrase from the source and cite it.",
        context="[1] Diagnostic source: AI Knowledge Inbox chat generation check passed.",
    )
    return {
        "provider_connectivity": "passed",
        "chat_generation_test": "passed" if answer.strip() else "failed",
        "chat_model": get_settings().openrouter_chat_model,
    }
