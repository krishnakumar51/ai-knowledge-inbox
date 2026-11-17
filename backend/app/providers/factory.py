from functools import lru_cache

from app.providers.openrouter import OpenRouterProvider


@lru_cache(maxsize=1)
def get_llm_provider() -> OpenRouterProvider:
    return OpenRouterProvider()
