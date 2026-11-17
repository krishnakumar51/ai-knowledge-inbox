from app.providers.factory import get_llm_provider


class EmbeddingService:
    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return get_llm_provider().embed_texts(texts)

    def embed_query(self, query: str) -> list[float]:
        return self.embed_text(query)
