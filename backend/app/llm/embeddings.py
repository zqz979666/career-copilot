"""Embedding service — text → vector for Profile semantic search (pgvector).

Uses OpenAI ``text-embedding-3-small`` (1536 dims). The service degrades
gracefully:

- If embeddings are disabled (``EMBEDDING_ENABLED=false``) or no OpenAI key is
  configured, :meth:`embed` returns ``None`` and callers store NULL vectors.
  Retrieval then falls back to keyword/recency ordering (see ProfileEngine).
- API failures are logged and swallowed (return ``None``) — embeddings are an
  optimisation, never a hard dependency of the write path.
"""
from __future__ import annotations

import time

from openai import AsyncOpenAI

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._enabled = settings.embedding_enabled and bool(api_key or settings.openai_api_key)
        self._client = AsyncOpenAI(
            api_key=api_key or settings.openai_api_key or None,
            timeout=30.0,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, text: str) -> list[float] | None:
        """Embed a single text. Returns ``None`` when disabled/unavailable."""
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else None

    async def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a batch. Returns ``None`` (not a partial) on any failure.

        Empty / whitespace-only inputs are replaced with a single space so the
        API doesn't reject the request; the resulting vector is harmless.
        """
        if not self._enabled or not texts:
            return None

        cleaned = [t.strip() or " " for t in texts]
        started = time.time()
        try:
            resp = await self._client.embeddings.create(model=self._model, input=cleaned)
        except Exception as e:  # noqa: BLE001
            logger.warning("embedding_failed", error=str(e), model=self._model, n=len(cleaned))
            return None

        vectors = [item.embedding for item in resp.data]
        logger.info(
            "embedding_ok",
            model=self._model,
            n=len(vectors),
            dim=len(vectors[0]) if vectors else 0,
            elapsed_ms=int((time.time() - started) * 1000),
        )
        return vectors
