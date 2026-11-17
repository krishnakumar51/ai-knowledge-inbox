import sys

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.services.embeddings import EmbeddingService


def main() -> int:
    settings = get_settings()
    try:
        vector = EmbeddingService().embed_text("AI Knowledge Inbox local embedding readiness check.")
    except ServiceUnavailableError as exc:
        print(f"Embedding check failed: {exc.message}", file=sys.stderr)
        if exc.__cause__ is not None:
            cause = exc.__cause__
            print(f"Cause: {type(cause).__name__}: {cause}", file=sys.stderr)
        return 1
    if len(vector) != settings.embedding_dimensions:
        print(
            f"Embedding check failed: expected {settings.embedding_dimensions} dimensions, received {len(vector)}",
            file=sys.stderr,
        )
        return 1
    print(f"Embedding check passed: model={settings.openrouter_embedding_model}, dimensions={len(vector)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
