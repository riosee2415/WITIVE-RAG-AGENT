"""In-memory fake Pinecone adapter for unit tests — no external SDK required.

Implements ``PineconeAdapter`` (``@runtime_checkable`` Protocol) with per-tenant
in-memory index.  Cosine similarity is computed directly.  The Pinecone filter
DSL is evaluated via ``tests.fakes._filter.eval_filter``.

Cross-tenant enforcement: any ``upsert`` or ``update_metadata`` call where
``metadata["tenant_id"]`` != ``str(ctx.tenant_id)`` raises
``TenantMismatchError`` immediately.

References:
  @docs/04-data-stores.md §1 (Pinecone schema, query patterns)
  @docs/07-multitenancy-and-access.md §2.2 (tenant_id enforcement)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.domain.tenant import TenantContext
from app.infra._base import TenantMismatchError
from app.infra.pinecone import QueryMatch, VectorRecord
from tests.fakes._filter import eval_filter

__all__ = ["FakePinecone"]


@dataclass(frozen=True)
class _Vector:
    """Internal representation of a stored Pinecone vector."""

    id: str
    values: tuple[float, ...]
    metadata: dict[str, Any]


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in ``[-1.0, 1.0]``.  Returns ``0.0`` for zero vectors.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _assert_vector_tenant(ctx: TenantContext, metadata: Mapping[str, Any]) -> None:
    """Raise ``TenantMismatchError`` if metadata tenant_id mismatches ctx.

    Args:
        ctx: The calling tenant context.
        metadata: Vector metadata to validate.

    Raises:
        TenantMismatchError: If ``metadata["tenant_id"]`` is absent or
            does not equal ``str(ctx.tenant_id)``.
    """
    meta_tid = metadata.get("tenant_id")
    if meta_tid != str(ctx.tenant_id):
        raise TenantMismatchError(
            resource="pinecone_vector_metadata",
            detail=(
                f"metadata.tenant_id={meta_tid!r} does not match ctx.tenant_id={ctx.tenant_id!r}"
            ),
        )


class FakePinecone:
    """In-memory fake implementation of ``PineconeAdapter``.

    Each tenant gets an isolated index (``dict[str, _Vector]``).  Physical
    index isolation mirrors the production ``witive-{tenant_id}`` pattern.

    Thread-safety: not guaranteed — use one instance per test coroutine.
    """

    def __init__(self) -> None:
        """Initialise empty per-tenant index store."""
        self._indexes: dict[UUID, dict[str, _Vector]] = {}

    def _index_for(self, tenant_id: UUID) -> dict[str, _Vector]:
        """Return (or create) the index for *tenant_id*."""
        if tenant_id not in self._indexes:
            self._indexes[tenant_id] = {}
        return self._indexes[tenant_id]

    async def query(
        self,
        ctx: TenantContext,
        vector: Sequence[float],
        top_k: int,
        filter: Mapping[str, Any],
        *,
        include_metadata: bool = True,  # noqa: ARG002
    ) -> Sequence[QueryMatch]:
        """Query the tenant's index for nearest neighbours.

        Applies *filter* using the Pinecone DSL evaluator, then ranks
        remaining vectors by cosine similarity descending.

        Args:
            ctx: Tenant context — determines which index to query.
            vector: Query embedding.
            top_k: Number of results to return.
            filter: Pinecone metadata filter dict.
            include_metadata: Included for protocol compliance; always ``True``
                in the fake.

        Returns:
            Up to *top_k* ``QueryMatch`` instances ordered by descending score.
        """
        index = self._index_for(ctx.tenant_id)
        candidates: list[tuple[float, _Vector]] = []
        for vec in index.values():
            if filter and not eval_filter(filter, vec.metadata):
                continue
            score = _cosine_similarity(vector, vec.values)
            candidates.append((score, vec))
        candidates.sort(key=lambda t: t[0], reverse=True)
        return [
            QueryMatch(id=vec.id, score=score, metadata=dict(vec.metadata))
            for score, vec in candidates[:top_k]
        ]

    async def upsert(
        self,
        ctx: TenantContext,
        vectors: Sequence[VectorRecord],
    ) -> None:
        """Upsert *vectors* into the tenant's index.

        All records must have ``metadata["tenant_id"] == str(ctx.tenant_id)``.
        A single mismatch aborts the entire batch (consistent with the real adapter).

        Args:
            ctx: Tenant context.
            vectors: Vector records to upsert.

        Raises:
            TenantMismatchError: If any vector's metadata ``tenant_id``
                does not match ``ctx.tenant_id``.
        """
        # Validate all before writing any (fail-fast, all-or-nothing)
        for rec in vectors:
            _assert_vector_tenant(ctx, rec.metadata)
        index = self._index_for(ctx.tenant_id)
        for rec in vectors:
            index[rec.id] = _Vector(
                id=rec.id,
                values=rec.values,
                metadata=dict(rec.metadata),
            )

    async def delete(
        self,
        ctx: TenantContext,
        vector_ids: Sequence[str],
    ) -> None:
        """Delete vectors by ID from the tenant's index.

        Args:
            ctx: Tenant context.
            vector_ids: IDs to delete.  Non-existent IDs are silently ignored.
        """
        index = self._index_for(ctx.tenant_id)
        for vid in vector_ids:
            index.pop(vid, None)

    async def update_metadata(
        self,
        ctx: TenantContext,
        vector_id: str,
        metadata: Mapping[str, Any],
    ) -> None:
        """Merge *metadata* into the existing metadata of *vector_id*.

        Args:
            ctx: Tenant context.
            vector_id: Target vector ID.
            metadata: New metadata fields to merge (shallow merge).

        Raises:
            TenantMismatchError: If ``metadata["tenant_id"]`` does not
                match ``ctx.tenant_id``.
        """
        _assert_vector_tenant(ctx, metadata)
        index = self._index_for(ctx.tenant_id)
        existing = index.get(vector_id)
        if existing is None:
            # No-op for missing IDs (mirrors real Pinecone behaviour)
            return
        merged = {**existing.metadata, **metadata}
        index[vector_id] = _Vector(
            id=existing.id,
            values=existing.values,
            metadata=merged,
        )
