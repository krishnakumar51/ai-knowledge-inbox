"""Short conversation titles derived from the first question, without an extra LLM call."""

import re
from collections.abc import Iterable
from uuid import UUID

from app.services.scope import _GENERIC, _MONTHS, _STOPWORDS, matched_keys, stem, tokens

DEFAULT_TITLE = "New conversation"
_EXTRA_FILLER = frozenset({"work", "working", "worked", "had", "get", "got", "make", "need", "want"})
MAX_LENGTH = 60


def _pretty(word: str) -> str:
    if len(word) <= 2 or word.isupper():
        return word.upper()
    return word[:1].upper() + word[1:]


def generate_title(question: str, candidates: Iterable[tuple[UUID, str, dict | None]] = ()) -> str:
    """e.g. "What's the budget revision for Project Atlas?" -> "Project Atlas — Budget Revision"."""
    label = ""
    key_terms: set[str] = set()
    for key in matched_keys(question, candidates):
        if len(key.split()) <= 3:  # short, human-sized project names only
            label = key
            key_terms = set(tokens(key))
            break
    words: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9]+", question):
        base = stem(word.lower())
        if (
            base in _STOPWORDS or base in _GENERIC or base in _MONTHS or base in _EXTRA_FILLER
            or base.isdigit() or len(base) < 2 or base in seen or base in key_terms
        ):
            continue
        seen.add(base)
        words.append(_pretty(word))
    if label:
        title = label + (" — " + " ".join(words[:2]) if words else "")
    elif words:
        title = " ".join(words[:4])
    else:
        title = question.strip()[:40] or DEFAULT_TITLE
    title = " ".join(title.split())
    return title[:MAX_LENGTH].rstrip()
