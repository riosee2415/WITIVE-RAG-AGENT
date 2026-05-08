"""Embeddings adapter protocol — Bedrock Titan text embedding operations.

Titan Embeddings v2 does not support batch input (one text per call).
``embed_batch`` hides this by running calls concurrently with
``asyncio.gather``; the implementation is responsible for respecting the
global rate limit via ``BEDROCK_TITAN_RPS_LIMIT`` (Redis-backed token bucket
or local fallback — see @docs/05-llm-bedrock.md §5.2).

No external SDK or ``aioboto3`` is imported here.

References:
  @docs/05-llm-bedrock.md §5 (Titan v2, batch strategy, timeout)
  @docs/03-document-pipeline.md §3.5 (embedding call pattern)
  @docs/08-resilience.md §4-5 (retry: 3x for indexing, 0x for query)
  @docs/12-coding-conventions.md §7.2 (Protocol for infra interfaces)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.domain.tenant import TenantContext

__all__ = ["EmbeddingsAdapter"]

#: Default model for all embedding calls.
#: Override via environment variable ``BEDROCK_MODEL_EMBEDDING``.
#: Reference: @docs/05-llm-bedrock.md §1.3
_DEFAULT_MODEL = "amazon.titan-embed-text-v2:0"

#: Output dimensionality for Titan Embeddings v2.
#: Reference: @docs/04-data-stores.md §1.1
EMBEDDING_DIMENSION: int = 1536


@runtime_checkable
class EmbeddingsAdapter(Protocol):
    """Async protocol for text embedding generation via Bedrock Titan v2.

    Both methods return ``tuple[float, ...]`` — an immutable, hashable
    sequence — rather than ``list[float]`` so that results can be stored
    in frozen dataclasses and used as dict keys in tests.

    **Output dimension**: 1 536 (Titan Embeddings v2 with ``normalize=True``).

    **Rate limiting** (@docs/05-llm-bedrock.md §5.2):
    Implementations must honour ``BEDROCK_TITAN_RPS_LIMIT`` (default 30 RPS)
    via a Redis-backed distributed token bucket (or a local per-task bucket
    when Redis is unavailable).

    **Timeout**: 5 s per SDK call (@docs/08-resilience.md §5.2).

    **Retry** (@docs/08-resilience.md §4):
    - Query-time single embedding: 0 retries (fail fast → Neo4j fallback).
    - Indexing batch: 3 retries with 1 s/2 s/4 s backoff + ±20 % jitter.
    """

    async def embed_batch(
        self,
        ctx: TenantContext,
        texts: Sequence[str],
        *,
        model: str = _DEFAULT_MODEL,
    ) -> Sequence[tuple[float, ...]]:
        """Generate embeddings for each text in *texts* concurrently.

        Titan v2 is single-input only; implementations run concurrent
        ``invoke_model`` calls bounded by the global rate limit
        (``EMBED_BATCH_SIZE=20``, ``MAX_CONCURRENT_EMBED_BATCHES=4``).

        Args:
            ctx: Tenant context (used for logging/metrics attribution).
            texts: Sequence of raw text strings to embed.  Each must be
                within the Titan v2 input limit (~8 192 tokens;
                @docs/05-llm-bedrock.md §5.4).
            model: Bedrock model ID (default Titan v2).  Must be the full
                model ID or inference profile ARN from ``BEDROCK_MODEL_EMBEDDING``.

        Returns:
            Sequence of 1 536-float tuples, in the same order as *texts*.

        Raises:
            InfraError: For any Bedrock/network failure after retries.
        """
        ...

    async def embed_single(
        self,
        ctx: TenantContext,
        text: str,
        *,
        model: str = _DEFAULT_MODEL,
    ) -> tuple[float, ...]:
        """Generate an embedding for a single text string.

        Used at query time to embed the (rewritten) user question before
        Pinecone nearest-neighbour search.

        Args:
            ctx: Tenant context (used for logging/metrics attribution).
            text: The text to embed.
            model: Bedrock model ID (default Titan v2).

        Returns:
            Tuple of 1 536 floats (cosine-normalised).

        Raises:
            InfraError: For any Bedrock/network failure (0 retries at
                query time — fail fast, caller falls back to Neo4j fulltext).
        """
        ...
