"""Import the backend/testdata/atlas_temporal_test.json fixture into the existing target account.

Uses the real IngestionService (chunks + embeddings). created_at is the real import time;
effective_at/metadata come from the file. Re-running skips already-imported notes.
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import AppError
from app.core.time import parse_import_timestamp
from app.db.session import get_engine
from app.models import Item, User
from app.models.item import SourceType
from app.schemas.ingest import IngestRequest
from app.services.ingestion import IngestionService


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


async def run(path: Path, dry_run: bool) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    dataset_id = data["dataset_name"]
    email = data["target_account"]["email"].strip().lower()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            print("Target account not found; refusing to create one.")
            return 1
        failed = 0
        for note in data["notes"]:
            external_id = slug(note["title"])
            exists = await db.scalar(
                select(Item.id).where(
                    Item.user_id == user.id, Item.dataset_id == dataset_id, Item.external_id == external_id
                )
            )
            if exists:
                print(f"skip   {external_id} (already imported)")
                continue
            if dry_run:
                print(f"would  {external_id} effective_at={parse_import_timestamp(note['effective_at'], naive_is_local=False)}")
                continue
            request = IngestRequest(
                source_type=SourceType.note,
                title=note["title"],
                content=note["content"],
                effective_at=parse_import_timestamp(note["effective_at"], naive_is_local=False),
                source_metadata=note.get("metadata", {}),
            )
            try:
                item = await IngestionService().ingest(
                    db, request, user.id, dataset_id=dataset_id, external_id=external_id
                )
                print(f"import {external_id} -> {item.status.value} {item.id}")
            except AppError as exc:
                failed += 1
                print(f"FAILED {external_id}: {exc.message}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(run(a.file, a.dry_run)))
