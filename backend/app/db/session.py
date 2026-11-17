from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError

_engine: AsyncEngine | None = None
_engine_url: str | None = None


def normalize_database_url(database_url: str) -> str:
    """Accept standard PostgreSQL URLs and select the installed asyncpg driver."""
    try:
        url = make_url(database_url)
    except (TypeError, ValueError) as exc:
        raise ServiceUnavailableError("DATABASE_URL is invalid; provide a PostgreSQL connection URL") from exc
    if url.drivername in {"postgres", "postgresql"} or url.drivername == "postgresql+psycopg2":
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        raise ServiceUnavailableError("DATABASE_URL must use PostgreSQL; SQLite is not supported")
    query = dict(url.query)
    if "channel_binding" in query:
        raise ServiceUnavailableError(
            "The asyncpg driver does not support the channel_binding URL option; use a direct asyncpg-compatible "
            "PostgreSQL URL with TLS configured through sslmode=require"
        )
    sslmode = query.pop("sslmode", None)
    if sslmode and "ssl" not in query:
        query["ssl"] = sslmode
    return url.set(query=query).render_as_string(hide_password=False)


def get_engine() -> AsyncEngine:
    global _engine, _engine_url
    configured_url = get_settings().database_url
    if not configured_url:
        raise ServiceUnavailableError("DATABASE_URL is not configured")
    normalized_url = normalize_database_url(configured_url)
    if _engine is not None and _engine_url != normalized_url:
        raise ServiceUnavailableError(
            "DATABASE_URL changed after database initialization; restart the application"
        )
    if _engine is None:
        try:
            _engine = create_async_engine(
                normalized_url,
                pool_pre_ping=True,
                connect_args={"timeout": 5},
            )
        except Exception as exc:
            raise ServiceUnavailableError(
                "DATABASE_URL could not initialize a PostgreSQL connection"
            ) from exc
        _engine_url = normalized_url
    return _engine


async def dispose_engine() -> None:
    global _engine, _engine_url
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _engine_url = None


async def get_db() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
