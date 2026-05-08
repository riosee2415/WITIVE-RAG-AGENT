"""In-memory fake Embeddings adapter for unit tests — no external SDK required.

Implements ``EmbeddingsAdapter`` (``@runtime_checkable`` Protocol) with
deterministic, SHA-256-seeded 1 536-dimensional unit vectors.  The same
text always produces the same vector, enabling reproducible tests.

References:
  @docs/04-data-stores.md §1.1 (dimension = 1 536)
  @docs/05-llm-bedrock.md §5 (Titan v2)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Final

from app.domain.tenant import TenantContext

__all__ = ["FakeEmbeddings"]

#: Output dimension — must match Titan v2 / Pinecone index configuration.
DIMENSION: Final[int] = 1536


def _deterministic_vector(text: str) -> tuple[float, ...]:
    """Generate a deterministic unit-norm 1 536-float embedding for *text*.

    Uses SHA-256 to produce a reproducible byte stream from which 1 536
    floats are derived by interpreting each byte as an unsigned integer and
    scaling to ``[-0.5, 0.5]``.  The result is normalised to unit length
    (L2 norm == 1.0).

    Using raw byte values avoids the NaN / Inf values that ``struct.unpack``
    can produce from arbitrary binary data when treating it as IEEE 754 floats.

    Args:
        text: Input text string.

    Returns:
        Tuple of 1 536 floats with L2 norm ≈ 1.0.
    """
    seed = text.encode("utf-8")
    # Collect bytes by iteratively hashing until we have enough
    byte_buf: bytearray = bytearray()
    digest = hashlib.sha256(seed).digest()
    while len(byte_buf) < DIMENSION:
        byte_buf.extend(digest)
        digest = hashlib.sha256(digest).digest()
    # Convert each byte to a float in [-0.5, 0.5]
    raw = [b / 255.0 - 0.5 for b in byte_buf[:DIMENSION]]
    # Normalise to unit length
    norm = math.sqrt(sum(x * x for x in raw))
    if norm == 0.0:
        # Fallback: distribute 1/sqrt(DIMENSION) uniformly (practically unreachable)
        uniform = 1.0 / math.sqrt(DIMENSION)
        return tuple(uniform for _ in range(DIMENSION))
    return tuple(x / norm for x in raw)


class FakeEmbeddings:
    """In-memory fake implementation of ``EmbeddingsAdapter``.

    All outputs are deterministic: identical input text always yields the
    same 1 536-dimensional unit vector.  Batch and single methods are
    consistent (``embed_batch([t]) == [embed_single(t)]``).

    Thread-safety: stateless; safe to share across coroutines.
    """

    #: Exposed dimension constant (mirrors ``EmbeddingsAdapter`` convention).
    dimension: Final[int] = DIMENSION

    async def embed_batch(
        self,
        ctx: TenantContext,  # noqa: ARG002
        texts: Sequence[str],
        *,
        model: str = "amazon.titan-embed-text-v2:0",  # noqa: ARG002
    ) -> Sequence[tuple[float, ...]]:
        """Return a deterministic embedding for each text in *texts*.

        Args:
            ctx: Tenant context (unused in the fake).
            texts: Sequence of input texts.
            model: Model ID (unused in the fake).

        Returns:
            Sequence of 1 536-float tuples, same order as *texts*.
        """
        return [_deterministic_vector(t) for t in texts]

    async def embed_single(
        self,
        ctx: TenantContext,  # noqa: ARG002
        text: str,
        *,
        model: str = "amazon.titan-embed-text-v2:0",  # noqa: ARG002
    ) -> tuple[float, ...]:
        """Return a deterministic embedding for a single *text*.

        Args:
            ctx: Tenant context (unused in the fake).
            text: Input text string.
            model: Model ID (unused in the fake).

        Returns:
            Tuple of 1 536 floats with unit L2 norm.
        """
        return _deterministic_vector(text)
