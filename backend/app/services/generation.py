import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import application_timezone, as_user_timezone
from app.providers.factory import get_llm_provider
from app.schemas.query import QueryResponse, SourceReference
from app.services.embeddings import EmbeddingService
from app.services.retrieval import RetrievalService


def temporal_intent(question: str, today: date | None = None) -> tuple[str, date | None]:
    """Return simple intent and an inclusive historical cutoff when the wording supplies one."""
    lowered = question.lower()
    if any(
        word in lowered
        for word in ("timeline", "chronology", "when did", "history of", "over time", "changes to")
    ):
        return "timeline", None
    if any(word in lowered for word in ("planned", "plan for", "upcoming", "future", "will be")):
        return "future", None
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lowered)
    if match:
        return "historical", date.fromisoformat(match.group(0))
    month_names = (
        "January|February|March|April|May|June|July|August|September|October|November|December|"
        "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    )
    match = re.search(rf"\b({month_names})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b", question, re.IGNORECASE)
    if match:
        today = today or datetime.now(UTC).date()
        year = int(match.group(3) or today.year)
        parsed = date(
            year,
            datetime.strptime(match.group(1), "%B" if len(match.group(1)) > 3 else "%b").month,
            int(match.group(2)),
        )
        if match.group(3) is None and parsed > today:
            parsed = parsed.replace(year=year - 1)
        return "historical", parsed
    if "last month" in lowered:
        today = today or datetime.now(UTC).date()
        first_this_month = today.replace(day=1)
        return "historical", first_this_month - timedelta(days=1)
    if any(
        word in lowered
        for word in ("as of", "on ", "before", "last year", "historically", "was my", "what was")
    ):
        # Historical wording without a parseable date must not be reranked as current.
        return "historical", None
    return "current", None


def _applicable_date(item) -> date:
    value = item.effective_at or item.created_at
    return value.astimezone(application_timezone()).date() if value else date.min


def keep_retrieved_citations(answer: str, sources: list[SourceReference]) -> str:
    """Convert source ordinals into item IDs and remove unrecognized citation labels."""
    item_ids = {str(source.item_id) for source in sources}
    ordinal_ids = {str(index): str(source.item_id) for index, source in enumerate(sources, 1)}

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        if label in ordinal_ids:
            return f"[{ordinal_ids[label]}]"
        try:
            normalized = str(UUID(label))
        except ValueError:
            return ""
        return f"[{normalized}]" if normalized in item_ids else ""

    return re.sub(r"\[([^\[\]]+)\]", replace, answer)


class QueryService:
    def __init__(self, embeddings: EmbeddingService | None = None, retrieval: RetrievalService | None = None):
        self.embeddings = embeddings or EmbeddingService()
        self.retrieval = retrieval or RetrievalService()

    async def answer(
        self, db: AsyncSession, user_id, question: str, top_k: int | None = None, history=None
    ) -> QueryResponse:
        count = top_k or get_settings().retrieval_top_k
        # Prior turns clarify pronouns, but only saved, retrieved sources can support facts.
        retrieval_question = question
        if history:
            prior_user_turns = [message["content"] for message in history if message.get("role") == "user"][
                -3:
            ]
            if prior_user_turns:
                retrieval_question = "\n".join(prior_user_turns + [question])
        intent, cutoff = temporal_intent(question)
        now = datetime.now(UTC)
        effective_before = None
        effective_after = None
        if intent == "current" or (intent == "historical" and cutoff is None):
            effective_before = now
        elif intent == "historical" and cutoff:
            local_exclusive = datetime.combine(cutoff + timedelta(days=1), datetime.min.time()).replace(
                tzinfo=application_timezone()
            )
            effective_before = local_exclusive.astimezone(UTC)
        elif intent == "future":
            effective_after = now
        vector = await asyncio.to_thread(self.embeddings.embed_query, retrieval_question)
        results = await self.retrieval.retrieve(
            db,
            user_id,
            vector,
            retrieval_question,
            count,
            effective_before=effective_before,
            effective_after=effective_after,
        )
        threshold = get_settings().retrieval_min_score
        results = [entry for entry in results if entry[2] >= threshold]
        if not results:
            return QueryResponse(
                answer="I couldn't find relevant information in your saved knowledge.", sources=[]
            )
        by_relevance = sorted(results, key=lambda entry: entry[2], reverse=True)
        if intent == "timeline":
            results = sorted(
                by_relevance, key=lambda entry: (_applicable_date(entry[1]), entry[1].created_at)
            )
        elif intent == "current":
            best_score = by_relevance[0][2]
            near_best = [entry for entry in by_relevance if best_score - entry[2] <= 0.08]
            other = [entry for entry in by_relevance if best_score - entry[2] > 0.08]
            results = (
                sorted(
                    near_best,
                    key=lambda entry: (_applicable_date(entry[1]), entry[1].created_at),
                    reverse=True,
                )
                + other
            )
        results = results[:count]
        sources = [
            SourceReference(
                item_id=item.id,
                title=item.title,
                source_url=item.source_url,
                chunk_id=chunk.id,
                excerpt=chunk.content[:500],
                effective_at=item.effective_at,
                created_at=item.created_at,
            )
            for chunk, item, _ in results
        ]
        context = "\n\n".join(
            f"[{i}] item_id={source.item_id} title={source.title} source_url={source.source_url or 'none'} "
            f"(effective_at={as_user_timezone(results[i - 1][1].effective_at).isoformat() if results[i - 1][1].effective_at else 'not supplied'}, "
            f"saved_at={as_user_timezone(results[i - 1][1].created_at).isoformat() if results[i - 1][1].created_at else 'unknown'}): "
            f"{source.excerpt}"
            for i, source in enumerate(sources, 1)
        )
        answer = await get_llm_provider().generate(question=question, context=context, history=history or [])
        return QueryResponse(answer=keep_retrieved_citations(answer, sources), sources=sources)
