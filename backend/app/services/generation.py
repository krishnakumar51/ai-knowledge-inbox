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
from app.services.scope import _GENERIC, _STOPWORDS, distinctive_terms, tokens

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
)
_MONTH_NUMBERS = {name: i for i, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
)}
_FUTURE_WORDS = ("plan for", "upcoming", "future", "will be", "planned for")


def _month_number(name: str) -> int:
    return _MONTH_NUMBERS[name[:3].lower()]


def _end_of_month(year: int, month: int) -> date:
    first_next = date(year + (month == 12), month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def temporal_intent(question: str, today: date | None = None) -> tuple[str, date | None]:
    """Return simple intent and an inclusive historical cutoff when the wording supplies one.

    An explicit date always wins over wording such as "planned", because "the planned launch
    date as of November 5" asks about a past state of a planned fact, not about the future.
    """
    lowered = question.lower()
    today = today or datetime.now(UTC).date()
    if any(
        word in lowered
        for word in (
            "timeline", "chronology", "when did", "when was", "when were", "history of",
            "over time", "changes to", "original", "originally", "initially", "earliest",
        )
    ):
        return "timeline", None
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lowered)
    if match:
        return "historical", date.fromisoformat(match.group(0))
    match = re.search(rf"\b({_MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", question, re.IGNORECASE)
    if match:
        year = int(match.group(3) or today.year)
        parsed = date(year, _month_number(match.group(1)), int(match.group(2)))
        # A year-less date far in the future most likely means last year; near-future dates
        # (e.g. an upcoming evaluation date) stay in the current year.
        if match.group(3) is None and parsed > today + timedelta(days=60):
            parsed = parsed.replace(year=year - 1)
        return "historical", parsed
    if any(word in lowered for word in _FUTURE_WORDS) or re.search(r"\bplanned\b", lowered):
        return "future", None
    match = re.search(rf"\b(?:in|during|by|as of|before)\s+({_MONTHS})\b(?:,?\s+(\d{{4}}))?", question, re.IGNORECASE)
    if match:
        year = int(match.group(2) or today.year)
        month = _month_number(match.group(1))
        cutoff = _end_of_month(year, month)
        if match.group(2) is None and cutoff > today + timedelta(days=60):
            cutoff = _end_of_month(year - 1, month)
        return "historical", cutoff
    if "last month" in lowered:
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


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def strip_internal_details(answer: str) -> str:
    """Remove leaked field names and bare UUIDs; bracketed [uuid] citations are kept for the UI."""
    answer = re.sub(r"[ \t]*[(,]?\s*effective_at\s*[=:]?\s*[0-9T:.+\-Z]+\)?", "", answer)
    answer = re.sub(rf"(?<!\[)\b{_UUID}\b(?!\])", "", answer)
    answer = re.sub(r"\b(?:item_id|chunk_id)\s*[=:]\s*", "", answer)
    return re.sub(r"[ \t]+\n", "\n", answer).strip()


def cited_sources(answer: str, sources: list[SourceReference]) -> list[SourceReference]:
    """Sources referenced by [item-uuid] labels in the answer, one per item, in order of first citation."""
    by_item: dict[str, SourceReference] = {}
    for source in sources:
        by_item.setdefault(str(source.item_id), source)
    cited: list[SourceReference] = []
    for label in re.findall(r"\[(" + _UUID + r")\]", answer):
        source = by_item.pop(label.lower(), None)
        if source is not None:
            cited.append(source)
    return cited


_NO_EVIDENCE = re.compile(
    r"(does not contain|do not contain|doesn.t contain|couldn.t find|could not find|no relevant|"
    r"not enough (information|evidence)|insufficient)",
    re.IGNORECASE,
)
GROUNDING_COVERAGE = 0.45
GROUNDING_MIN_MATCHES = 3


def _content_words(text: str) -> set[str]:
    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # 500,000 -> 500000
    return {t for t in tokens(text) if t not in _STOPWORDS and t not in _GENERIC and len(t) > 1}


def ground_sources(answer: str, sources: list[SourceReference], already: list[SourceReference]) -> tuple[str, list[SourceReference]]:
    """Attach sources the answer is demonstrably built from, even if the model forgot to cite them.

    A chunk supports the answer when most of its distinctive words (names, numbers, key terms) appear
    in the answer. Supporting sources get an inline [item-uuid] marker on the answer line that overlaps
    them most, so markers and the source list always agree. Unrelated retrieved chunks never qualify.
    """
    answer_words = _content_words(answer)
    result = list(already)
    seen = {str(source.item_id) for source in already}
    lines = answer.split("\n")
    for source in sources:
        item = str(source.item_id)
        if item in seen:
            continue
        chunk_words = _content_words(source.excerpt)
        matched = chunk_words & answer_words
        if len(matched) < GROUNDING_MIN_MATCHES or len(matched) / max(len(chunk_words), 1) < GROUNDING_COVERAGE:
            continue
        seen.add(item)
        result.append(source)
        scored = [(len(matched & _content_words(line)), index) for index, line in enumerate(lines) if line.strip()]
        if scored:
            best = max(scored)[1]
            lines[best] = lines[best].rstrip() + f" [{item}]"
    return "\n".join(lines), result


def attach_sources(answer: str, sources: list[SourceReference]) -> tuple[str, list[SourceReference]]:
    """Final answer text plus exactly the supporting sources (model-cited, then evidence-grounded)."""
    cited = cited_sources(answer, sources)
    if not cited and _NO_EVIDENCE.search(answer):
        return answer, []  # an honest "not enough information" answer gets no sources
    return ground_sources(answer, sources, cited)


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
            focus=question if distinctive_terms(question) else retrieval_question,
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
        elif intent in {"current", "historical"}:
            # Several versions of one fact can match; put the newest applicable one first.
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
            f"[{i}] title: {source.title} | source_url: {source.source_url or 'none'} | "
            f"applies from: {as_user_timezone(results[i - 1][1].effective_at).strftime('%d %B %Y') if results[i - 1][1].effective_at else 'not supplied'} | "
            f"saved on: {as_user_timezone(results[i - 1][1].created_at).strftime('%d %B %Y') if results[i - 1][1].created_at else 'unknown'}\n"
            f"text: "
            f"{source.excerpt}"
            for i, source in enumerate(sources, 1)
        )
        answer = await get_llm_provider().generate(question=question, context=context, history=history or [])
        cleaned = strip_internal_details(keep_retrieved_citations(answer, sources))
        # Return only sources that genuinely support the answer (retrieved-but-unused chunks are dropped).
        final_answer, supporting = attach_sources(cleaned, sources)
        return QueryResponse(answer=final_answer, sources=supporting)
