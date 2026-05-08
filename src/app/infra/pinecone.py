"""Pinecone adapter protocol — vector database operations with tenant isolation.

``upsert`` and ``update_metadata`` enforce tenant isolation by comparing
``metadata["tenant_id"]`` against ``str(ctx.tenant_id)``.  Query and delete
operations rely on the physical per-tenant index isolation described in
@docs/04-data-stores.md §1.1 (``witive-{tenant_id}`` index naming).

No external SDK is imported here — this module contains only the Protocol
definition and supporting frozen dataclasses.

References:
  @docs/04-data-stores.md §1 (Pinecone schema, patterns, timeout/retry)
  @docs/07-multitenancy-and-access.md §2.2 (tenant_id enforcement)
  @docs/08-resilience.md §4-5 (Pinecone retry/timeout)
  @docs/12-coding-conventions.md §7.2 (Protocol for infra interfaces)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.domain.tenant import TenantContext
from app.infra._base import TenantMismatchError

__all__ = ["PineconeAdapter", "QueryMatch", "VectorRecord"]


@dataclass(frozen=True)
class VectorRecord:
    """A single vector to be upserted into Pinecone.

    The ``metadata`` mapping must include a ``"tenant_id"`` key whose value
    equals ``str(ctx.tenant_id)``; the adapter validates this before any SDK
    call.  Use ``tuple[float, ...]`` (not ``list``) for ``values`` to keep the
    record hashable and immutable.

    Attributes:
        id: Vector identifier, e.g. ``"{doc_id}:{version}:{chunk_index}"``
            or ``"stg:{job_id}:{chunk_index}"`` during staging.
        values: Embedding values (1 536 dimensions for Titan v2).
        metadata: Pinecone metadata dict.  Must contain ``"tenant_id"``.

    References: @docs/04-data-stores.md §1.3 (metadata schema), §1.5 (IDs)
    """

    id: str
    values: tuple[float, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class QueryMatch:
    """A single result item returned by Pinecone query.

    Attributes:
        id: Vector identifier of the matching record.
        score: Cosine similarity score (0.0-1.0 for normalised vectors).
        metadata: Pinecone metadata dict associated with the record.

    References: @docs/04-data-stores.md §1.4 (query pattern)
    """

    id: str
    score: float
    metadata: Mapping[str, Any]


def _assert_vector_tenant(ctx: TenantContext, metadata: Mapping[str, Any]) -> None:
    """Raise ``TenantMismatchError`` when metadata tenant_id != ctx.tenant_id.

    Args:
        ctx: The calling tenant context.
        metadata: The vector metadata mapping to validate.

    Raises:
        TenantMismatchError: If ``metadata["tenant_id"]`` is missing or does
            not equal ``str(ctx.tenant_id)``.
    """
    meta_tid = metadata.get("tenant_id")
    if meta_tid != str(ctx.tenant_id):
        raise TenantMismatchError(
            resource="pinecone_vector_metadata",
            detail=(
                f"metadata.tenant_id={meta_tid!r} does not match ctx.tenant_id={ctx.tenant_id!r}"
            ),
        )


@runtime_checkable
class PineconeAdapter(Protocol):
    """Async protocol for Pinecone vector database operations.

    Tenant isolation relies on **physical index isolation** (one index per
    tenant; @docs/04-data-stores.md §1.1).  Metadata ``tenant_id`` is an
    audit/safety field only — it is not used as a query filter.

    Write operations (``upsert``, ``update_metadata``) additionally validate
    that ``metadata["tenant_id"]`` matches ``ctx.tenant_id`` and raise
    ``TenantMismatchError`` on mismatch.

    Batch size for ``upsert`` and ``delete``: 100 vectors per call (caller
    responsibility per @docs/04-data-stores.md §1.5).

    Timeout/retry policy per @docs/04-data-stores.md §1.6 and
    @docs/08-resilience.md §4-5 — enforced by implementations.
    """

    async def query(
        self,
        ctx: TenantContext,
        vector: Sequence[float],
        top_k: int,
        filter: Mapping[str, Any],
        *,
        include_metadata: bool = True,
    ) -> Sequence[QueryMatch]:
        """Query the tenant's Pinecone index for nearest neighbours.

        Args:
            ctx: Tenant context — determines which index to query.
            vector: Query embedding (1 536 floats for Titan v2).
            top_k: Number of nearest neighbours to return.
            filter: Pinecone metadata filter dict (see @docs/04 §1.4 for
                the full access-level filter pattern).
            include_metadata: Whether to include metadata in results.

        Returns:
            Sequence of ``QueryMatch`` ordered by descending score.

        Raises:
            InfraError: For any Pinecone/network failure (timeout: 500 ms,
                0 retries — fail immediately, caller falls back to Neo4j).
        """
        ...

    async def upsert(
        self,
        ctx: TenantContext,
        vectors: Sequence[VectorRecord],
    ) -> None:
        """Upsert *vectors* into the tenant's Pinecone index.

        All records in *vectors* must have ``metadata["tenant_id"] ==
        str(ctx.tenant_id)``; a single mismatch aborts the entire batch.

        Recommended batch size is 100 (caller responsibility).

        Args:
            ctx: Tenant context — determines which index to write to.
            vectors: Sequence of ``VectorRecord`` instances to upsert.

        Raises:
            TenantMismatchError: If any vector's metadata ``tenant_id``
                does not match ``ctx.tenant_id``.
            InfraError: For any Pinecone/network failure (timeout: 2 s,
                3 retries with 250 ms/500 ms/1 s exponential backoff).
        """
        ...

    async def delete(
        self,
        ctx: TenantContext,
        vector_ids: Sequence[str],
    ) -> None:
        """Delete vectors by ID from the tenant's Pinecone index.

        Args:
            ctx: Tenant context — determines which index to delete from.
            vector_ids: IDs to delete (up to 100 per call, caller
                responsibility).

        Raises:
            InfraError: For any Pinecone/network failure (timeout: 1 s,
                3 retries with 250 ms/500 ms/1 s backoff).
        """
        ...

    async def update_metadata(
        self,
        ctx: TenantContext,
        vector_id: str,
        metadata: Mapping[str, Any],
    ) -> None:
        """Update the metadata of a single vector (one record only).

        Used exclusively for the async post-processing step that sets
        ``is_current=false`` on old-version vectors after Stage B completes.
        Bulk transitions use the upsert+delete swap pattern instead
        (see @docs/04-data-stores.md §1.5 — Pinecone SDK batch update limit).

        Args:
            ctx: Tenant context — determines which index to update.
            vector_id: ID of the vector to update.
            metadata: Replacement metadata mapping.  Must contain
                ``"tenant_id"`` equal to ``str(ctx.tenant_id)``.

        Raises:
            TenantMismatchError: If ``metadata["tenant_id"]`` does not match
                ``ctx.tenant_id``.
            InfraError: For any Pinecone/network failure (timeout: 1 s,
                3 retries — failure OK, next reindex corrects it).
        """
        ...
