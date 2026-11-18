"""Question analysis for retrieval: distinctive search terms and named-project scoping.

Pure functions (no I/O) so they are cheap to test. Nothing here is specific to any dataset: a
"project key" is derived from each saved item (metadata ``project`` if present, otherwise the title
before " - ", otherwise the whole title), and a question *names* a project when it contains enough of
that key's distinctive words.
"""

import re
from collections.abc import Iterable
from uuid import UUID

_STOPWORDS = frozenset(
    ["a", "about", "above", "after", "again", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "me", "more", "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "give", "tell", "show", "please", "let", "know"]
)
# Words that describe the *kind* of request or item rather than a particular entity.
_GENERIC = frozenset(
    ["project", "projects", "recent", "recently", "latest", "update", "updates", "updated", "happening", "happen", "happened", "details", "detail", "info", "information", "note", "notes", "summary", "summarize", "summarise", "current", "currently", "today", "status", "progress", "new", "news", "item", "items", "saved", "library", "everything", "anything", "something", "related", "regarding", "compare", "comparison", "versus", "vs", "between", "difference", "differences", "list", "overview"]
)
_MONTHS = frozenset(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"]
)


def stem(token: str) -> str:
    """Very light plural folding ("automations" -> "automation"); good enough for name matching."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    return [stem(part) for part in re.findall(r"[a-z0-9]+", text.lower())]


def distinctive_terms(question: str) -> list[str]:
    """Words that identify what the question is about (no stopwords, request words, months, numbers)."""
    seen: list[str] = []
    for token in tokens(question):
        if (
            token in _STOPWORDS
            or token in _GENERIC
            or token in _MONTHS
            or token.isdigit()
            or len(token) < 2
            or token in seen
        ):
            continue
        seen.append(token)
    return seen


def project_key(title: str, metadata: dict | None) -> str:
    project = (metadata or {}).get("project")
    if isinstance(project, str) and project.strip():
        return project.strip()
    head = title.split(" - ", 1)[0].strip()
    return head or title.strip()


def _key_terms(key: str) -> set[str]:
    return {token for token in tokens(key) if token not in _STOPWORDS and token not in _GENERIC}


def matched_keys(question: str, candidates: Iterable[tuple[UUID, str, dict | None]]) -> dict[str, list[UUID]]:
    """Project keys named by the question, mapped to the ids of their items."""
    wanted = set(distinctive_terms(question))
    if not wanted:
        return {}
    by_key: dict[str, list[UUID]] = {}
    for item_id, title, metadata in candidates:
        by_key.setdefault(project_key(title, metadata), []).append(item_id)
    matched: dict[str, list[UUID]] = {}
    for key, item_ids in by_key.items():
        terms = _key_terms(key)
        if terms and len(terms & wanted) >= min(2, len(terms)):
            matched[key] = item_ids
    return matched


def detect_scope(question: str, candidates: Iterable[tuple[UUID, str, dict | None]]) -> set[UUID]:
    """Return ids of items belonging to projects/entities the question explicitly names.

    A key matches when the question contains all of its distinctive words (single-word keys) or at
    least two of them (longer keys), so a lone word like "AI" does not select a project, and broad
    questions ("all my AI projects") stay unscoped.
    """
    return {item_id for ids in matched_keys(question, candidates).values() for item_id in ids}


def or_tsquery(terms: list[str]) -> str:
    """OR-joined tsquery text built only from [a-z0-9] terms (safe to pass to to_tsquery)."""
    return " | ".join(term for term in terms if re.fullmatch(r"[a-z0-9]+", term))
