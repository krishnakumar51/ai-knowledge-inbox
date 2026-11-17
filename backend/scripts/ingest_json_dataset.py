import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import AppError
from app.db.session import get_engine
from app.models import Item, User
from app.schemas.dataset import HistoricalDataset
from app.schemas.ingest import IngestRequest
from app.services.ingestion import IngestionService

logger = logging.getLogger(__name__)


def _validation_summary(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"field": ".".join(str(part) for part in error["loc"]), "error": error["type"]}
        for error in exc.errors()
    ]


async def ingest_file(file_path: Path, *, dry_run: bool = False) -> dict:
    try:
        payload = HistoricalDataset.model_validate_json(file_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            return {"status": "invalid_dataset", "errors": _validation_summary(exc)}
        return {"status": "invalid_dataset", "error": type(exc).__name__}

    email = payload.user_email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return {"status": "invalid_dataset", "error": "user_email is invalid"}
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    result: dict = {"dataset_id": payload.dataset_id, "dry_run": dry_run, "records": []}
    async with session_factory() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            return {"status": "user_not_found", "dataset_id": payload.dataset_id}
        for item in payload.items:
            existing = await db.scalar(
                select(Item).where(
                    Item.user_id == user.id,
                    Item.dataset_id == payload.dataset_id,
                    Item.external_id == item.external_id,
                )
            )
            if existing is not None:
                result["records"].append(
                    {"external_id": item.external_id, "status": "skipped", "reason": "already_imported"}
                )
                continue
            if dry_run:
                result["records"].append({"external_id": item.external_id, "status": "would_import"})
                continue
            request = IngestRequest(
                source_type=item.source_type,
                title=item.title,
                content=item.content,
                source_url=item.source_url,
                effective_at=item.effective_at,
                source_metadata=item.source_metadata,
            )
            try:
                saved = await IngestionService().ingest(
                    db,
                    request,
                    user.id,
                    imported_created_at=item.created_at,
                    dataset_id=payload.dataset_id,
                    external_id=item.external_id,
                )
                result["records"].append(
                    {"external_id": item.external_id, "status": saved.status.value, "item_id": str(saved.id)}
                )
            except AppError as exc:
                await db.rollback()
                result["records"].append(
                    {"external_id": item.external_id, "status": "failed", "error": exc.message}
                )
            except SQLAlchemyError as exc:
                await db.rollback()
                logger.warning("Historical import record failed (%s)", type(exc).__name__)
                result["records"].append(
                    {"external_id": item.external_id, "status": "failed", "error": "database_error"}
                )
    result["summary"] = {
        "imported": sum(record["status"] == "ACTIVE" for record in result["records"]),
        "skipped": sum(record["status"] == "skipped" for record in result["records"]),
        "would_import": sum(record["status"] == "would_import" for record in result["records"]),
        "failed": sum(record["status"] == "failed" for record in result["records"]),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a timestamped JSON dataset for an existing user.")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing any data.")
    args = parser.parse_args()
    try:
        result = asyncio.run(ingest_file(args.file, dry_run=args.dry_run))
    except AppError as exc:
        print(json.dumps({"status": "failed", "error": exc.message}, ensure_ascii=False))
        return 1
    except SQLAlchemyError as exc:
        print(json.dumps({"status": "database_error", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in {"invalid_dataset", "user_not_found"} or result.get("summary", {}).get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
