from typing import Protocol


class LLMProvider(Protocol):
    async def generate(self, *, question: str, context: str, history: list[dict] | None = None) -> str: ...
