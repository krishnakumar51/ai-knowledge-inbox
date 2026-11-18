"""Run the Project Atlas temporal questions through the real QueryService, showing retrieval details."""

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import ServiceUnavailableError
from app.db.session import get_engine
from app.models import User
from app.services.generation import QueryService, temporal_intent

EMAIL = "godkrishnasskal@gmail.com"
# (question, expected source titles (substrings), expected facts in answer)
CASES = [
    ("What was the Project Atlas budget on September 15, 2026?", ["Initial Budget"], ["500000"], ["750000"]),
    ("What was the Project Atlas budget on October 15, 2026?", ["Revised Budget"], ["750000"], []),
    ("What was the original planned launch date?", ["Original Launch"], ["2026-11-10", "November 10"], []),
    ("What was the planned launch date as of November 5, 2026?", ["Launch Postponement"], ["2026-12-05", "December 5"], []),
    ("When was pgvector introduced?", ["Vector Search"], ["October 18", "2026-10-18", "18 October"], []),
    ("Who owned the backend and frontend work in September?", ["Initial Team Ownership"], ["platform team"], ["product engineering team"]),
    ("Who owned both implementations as of November 5?", ["Ownership Reassignment"], ["product engineering"], []),
    ("What was the retrieval target on November 5?", ["Initial Retrieval"], ["80"], ["92"]),
    ("What is the latest retrieval target?", ["Updated Retrieval"], ["92"], []),
    ("What retrieval target applies to the November 25 evaluation?", ["Updated Retrieval"], ["92"], []),
]


import sys

sys.stdout.reconfigure(encoding="utf-8")


async def main() -> None:
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == EMAIL))
        passed = 0
        for n, (q, src, facts, forbidden) in enumerate(CASES, 1):
            intent = temporal_intent(q)
            for attempt in range(6):
                try:
                    res = await QueryService().answer(db, user.id, q)
                    break
                except ServiceUnavailableError:
                    await asyncio.sleep(20 * (attempt + 1))
            else:
                print(f"#{n} {q} -> PROVIDER UNAVAILABLE")
                continue
            titles = [s.title for s in res.sources]
            src_ok = any(src[0] in t for t in titles)
            ans = res.answer.lower().replace(",", "")
            fact_ok = any(f.lower() in ans for f in facts) and not any(f.lower() in ans for f in forbidden)
            passed += src_ok and fact_ok
            print(f"\n#{n} {q}\n  intent={intent}")
            for s in res.sources:
                print(f"  src: {s.title} eff={s.effective_at}")
            print(f"  answer: {res.answer}\n  top_source_ok={src_ok} answer_ok={fact_ok}")
        print(json.dumps({"passed": passed, "total": len(CASES)}))


asyncio.run(main())
