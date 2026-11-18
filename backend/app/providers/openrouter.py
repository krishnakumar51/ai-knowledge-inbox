import logging
import math

from openai import APIConnectionError, APIError, APIStatusError, AsyncOpenAI, OpenAI, RateLimitError

from app.core.config import get_settings
from app.core.exceptions import ProviderError, ServiceUnavailableError

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openrouter_chat_model
        self.embedding_model = settings.openrouter_embedding_model
        self.embedding_dimensions = settings.embedding_dimensions
        self.client = None
        self.embedding_client = None
        if settings.openrouter_api_key:
            self.client = AsyncOpenAI(
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                timeout=settings.openrouter_timeout_seconds,
                max_retries=2,
            )
            self.embedding_client = OpenAI(
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                timeout=settings.openrouter_timeout_seconds,
                max_retries=2,
            )

    async def generate(self, *, question: str, context: str, history: list[dict] | None = None) -> str:
        if self.client is None or not self.model:
            raise ServiceUnavailableError(
                "Answer generation requires OPENROUTER_API_KEY and OPENROUTER_CHAT_MODEL"
            )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Answer questions about the user's saved knowledge only from the retrieved sources below. Conversation history may clarify references but is not evidence. Never infer facts absent from the source text. If the retrieved text does not contain the answer, say that the saved knowledge does not contain sufficient information. Each source shows the date it 'applies from'. A fact stays true until a later-effective source replaces it, so for a question about a specific date use the newest source effective on or before that date and ignore later ones; for 'original' or 'initial' questions use the earliest source; for 'latest' or 'current' questions use the newest. When asked when something was introduced, added or changed, the 'applies from' date of the source that first states it is the date. Mention superseded values only when they help. Only report a genuine conflict when two sources with the same effective date disagree. Cite only using the supplied numeric labels such as [1], [2]; never print ids, field names or raw timestamps, and write dates in plain words (e.g. 1 September 2026). Stay on the project or entity the question names: ignore sources about other projects unless the question asks to compare or cover several. If the sources do not support an answer about that entity, say the saved knowledge does not contain it. End every sentence or bullet that states a fact with its source label, e.g. [1]. Style: start with the direct answer; keep simple answers to a sentence or two; use bullet points for several facts, a chronological list for timelines and a markdown table for comparisons; do not repeat yourself or add filler introductions or closing offers.",
                    },
                    *[
                        message
                        for message in (history or [])[-10:]
                        if message.get("role") in {"user", "assistant"}
                    ],
                    {
                        "role": "user",
                        "content": f"Retrieved saved sources:\n{context}\n\nCurrent question: {question}",
                    },
                ],
                temperature=get_settings().openrouter_temperature,
            )
            if not response.choices or response.choices[0].message is None:
                raise ProviderError("OpenRouter returned no assistant message")
            answer = response.choices[0].message.content
            if isinstance(answer, list):
                answer = "".join(
                    part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                    for part in answer
                )
            if not isinstance(answer, str) or not answer.strip():
                raise ProviderError("The answer provider returned an empty response")
            return answer.strip()
        except RateLimitError as exc:
            logger.warning("OpenRouter rate limit reached")
            raise ServiceUnavailableError("OpenRouter rate limit reached; retry later") from exc
        except APIStatusError as exc:
            logger.error("OpenRouter request failed with status %s", exc.status_code)
            if exc.status_code in (402, 403):
                raise ServiceUnavailableError("OpenRouter credits or account access are unavailable") from exc
            if exc.status_code == 404:
                raise ServiceUnavailableError("The configured OpenRouter model is unavailable") from exc
            raise ProviderError("OpenRouter could not generate an answer") from exc
        except APIConnectionError as exc:
            logger.warning("OpenRouter connection failed")
            raise ServiceUnavailableError("OpenRouter is temporarily unavailable") from exc
        except APIError as exc:
            logger.warning("OpenRouter returned an invalid chat response (%s)", type(exc).__name__)
            raise ProviderError("OpenRouter returned an invalid chat response") from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.embedding_client is None:
            raise ServiceUnavailableError("Embeddings require OPENROUTER_API_KEY")
        if not self.embedding_model:
            raise ServiceUnavailableError("Embeddings require OPENROUTER_EMBEDDING_MODEL")
        try:
            response = self.embedding_client.embeddings.create(model=self.embedding_model, input=texts)
            ordered = sorted(response.data, key=lambda row: row.index)
            vectors = [[float(value) for value in row.embedding] for row in ordered]
            if len(vectors) != len(texts):
                raise ProviderError("OpenRouter returned an unexpected number of embeddings")
            if any(len(vector) != self.embedding_dimensions for vector in vectors):
                raise ProviderError(
                    f"OpenRouter embedding dimension mismatch; expected {self.embedding_dimensions}"
                )
            if any(not math.isfinite(value) for vector in vectors for value in vector):
                raise ProviderError("OpenRouter returned non-finite embedding values")
            return vectors
        except RateLimitError as exc:
            logger.warning("OpenRouter embedding rate limit reached")
            raise ServiceUnavailableError("OpenRouter embedding rate limit reached; retry later") from exc
        except APIStatusError as exc:
            logger.error("OpenRouter embedding request failed with status %s", exc.status_code)
            if exc.status_code in (401, 402, 403):
                raise ServiceUnavailableError(
                    "OpenRouter embedding access or credits are unavailable"
                ) from exc
            if exc.status_code == 404:
                raise ServiceUnavailableError(
                    "The configured OpenRouter embedding model is unavailable"
                ) from exc
            raise ProviderError("OpenRouter could not generate embeddings") from exc
        except APIConnectionError as exc:
            logger.warning("OpenRouter embedding connection failed")
            raise ServiceUnavailableError("OpenRouter embeddings are temporarily unavailable") from exc
        except APIError as exc:
            logger.warning("OpenRouter returned an invalid embedding response (%s)", type(exc).__name__)
            raise ProviderError("OpenRouter returned an invalid embedding response") from exc
