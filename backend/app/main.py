from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import auth, conversations, ingest, items, query
from app.api.routes import health as health_routes
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.db.session import dispose_engine

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Deliberately no database, model, or provider calls at startup.
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}}
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException):
    code = "not_found" if exc.status_code == 404 else "http_error"
    return JSONResponse(
        status_code=exc.status_code, content={"error": {"code": code, "message": str(exc.detail)}}
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_: Request, exc: SQLAlchemyError):
    # Deliberately do not stringify the driver exception: it may include connection details.
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "PostgreSQL is unavailable; check DATABASE_URL, network access, credentials, and server status.",
            }
        },
    )


@app.exception_handler(OSError)
async def database_connection_error_handler(_: Request, exc: OSError):
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "PostgreSQL is unavailable; check DATABASE_URL, network access, credentials, and server status.",
            }
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(ingest.router, prefix=settings.api_v1_prefix, tags=["ingestion"])
app.include_router(items.router, prefix=settings.api_v1_prefix, tags=["items"])
app.include_router(query.router, prefix=settings.api_v1_prefix, tags=["query"])
app.include_router(health_routes.router, tags=["health"])
app.include_router(auth.router, prefix=settings.api_v1_prefix, tags=["authentication"])
app.include_router(conversations.router, prefix=settings.api_v1_prefix, tags=["conversations"])
