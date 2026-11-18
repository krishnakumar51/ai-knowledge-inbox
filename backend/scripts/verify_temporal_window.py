"""Offline check (no OpenRouter calls) that the Atlas questions map to the right date window.

For each question it prints the parsed intent/cutoff, the exact retrieval window that
QueryService would apply, and the set of the user's items that pass the window filter in SQL
(RetrievalService with a constant dummy vector; the keyword branch is real full-text search).
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.time import application_timezone
from app.db.session import get_engine
from app.models import User
from app.services.generation import temporal_intent
from app.services.retrieval import RetrievalService

sys.stdout.reconfigure(encoding="utf-8")
EMAIL = "godkrishnasskal@gmail.com"
# question -> titles that MUST be inside the window / MUST be excluded
CASES = [
    ("What was the Project Atlas budget on September 15, 2026?", ["Initial Budget"], ["Revised Budget"]),
    ("What was the Project Atlas budget on October 15, 2026?", ["Initial Budget", "Revised Budget"], ["Launch Postponement"]),
    ("What was the original planned launch date?", ["Original Launch Date", "Launch Postponement"], []),
    ("What was the planned launch date as of November 5, 2026?", ["Original Launch Date", "Launch Postponement"], ["Updated Retrieval Target"]),
    ("When was pgvector introduced?", ["Vector Search Added"], []),
    ("Who owned the backend and frontend work in September?", ["Initial Team Ownership"], ["Ownership Reassignment"]),
    ("Who owned both implementations as of November 5?", ["Ownership Reassignment"], ["Updated Retrieval Target"]),
    ("What was the retrieval target on November 5?", ["Initial Retrieval Target"], ["Updated Retrieval Target"]),
    ("What is the latest retrieval target?", ["Updated Retrieval Target"], []),
    ("What retrieval target applies to the November 25 evaluation?", ["Updated Retrieval Target"], []),
]


async def main() -> int:
    dims = get_settings().embedding_dimensions
    dummy = [1.0] * dims
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    bad = 0
    async with factory() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == EMAIL))
        now = datetime.now(UTC)
        for n, (question, must, excluded) in enumerate(CASES, 1):
            intent, cutoff = temporal_intent(question)
            before = after = None
            if intent == "current" or (intent == "historical" and cutoff is None):
                before = now
            elif intent == "historical":
                before = (
                    datetime.combine(cutoff + timedelta(days=1), datetime.min.time())
                    .replace(tzinfo=application_timezone())
                    .astimezone(UTC)
                )
            elif intent == "future":
                after = now
            rows = await RetrievalService().retrieve(
                db, user.id, dummy, question, 10, effective_before=before, effective_after=after
            )
            titles = [item.title.replace("Project Atlas - ", "") for _, item, _ in rows]
            missing = [t for t in must if t not in titles]
            leaked = [t for t in excluded if t in titles]
            ok = not missing and not leaked
            bad += not ok
            print(f"#{n} {question}\n   intent={intent} cutoff={cutoff} window<{before} >{after}")
            print(f"   in window: {sorted(set(titles))}\n   missing={missing} leaked={leaked} -> {'PASS' if ok else 'FAIL'}")
    print(f"window failures: {bad}")
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
