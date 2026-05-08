"""Neo4j adapter protocol — graph database read/write operations.

All methods automatically map the tenant to the logical database
``tenant_{tenant_id_hex}`` (UUID with dashes removed) as described in
@docs/04-data-stores.md §2.1.  The mapping is the responsibility of
adapter implementations — callers never specify a database name directly.

Tenant isolation relies on the per-tenant logical database; params may
carry a ``tenant_id`` parameter for additional safety in queries, but the
database-level routing is the primary isolation mechanism.

No external ``neo4j`` SDK is imported — only Protocol definitions live here.

References:
  @docs/04-data-stores.md §2 (Neo4j schema, naming, timeout/retry)
  @docs/08-resilience.md §4-5 (Neo4j retry/timeout policy)
  @docs/12-coding-conventions.md §7.2 (Protocol for infra interfaces)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, TypeVar, runtime_checkable

from app.domain.tenant import TenantContext

__all__ = ["Neo4jAdapter", "Transaction"]

T = TypeVar("T")


@runtime_checkable
class Transaction(Protocol):
    """Protocol for an active Neo4j async transaction handle.

    Passed to the ``work`` callable in ``Neo4jAdapter.run_in_transaction``.
    Implementations wrap the driver's async transaction session so that
    callers can execute multiple Cypher statements atomically.
    """

    async def run(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Execute a Cypher statement within the current transaction.

        Args:
            cypher: The Cypher query string.
            params: Optional parameter mapping referenced by ``$name`` in
                the Cypher string.

        Returns:
            Sequence of result records, each as an immutable mapping of
            field name → value.

        Raises:
            InfraError: For any Neo4j driver or network failure.
        """
        ...


@runtime_checkable
class Neo4jAdapter(Protocol):
    """Async protocol for Neo4j graph database operations.

    **Database routing**: every method automatically derives the target
    database name as ``tenant_{tenant_id.hex}`` from ``ctx.tenant_id``.
    Adapter implementations must never allow callers to specify a database
    name directly.

    **Tenant safety in params**: implementations inject
    ``{"tenant_id": str(ctx.tenant_id)}`` into *params* before execution
    so that Cypher queries can reference ``$tenant_id`` without relying on
    the caller to supply it.

    Timeout and retry policy (@docs/08-resilience.md §4-5 and
    @docs/04-data-stores.md §2.6):
    - read queries: 1 000 ms, 0 retries (fail → Pinecone fallback)
    - write transactions: 5 s, driver-managed TransientError retry
    """

    async def run_read(
        self,
        ctx: TenantContext,
        cypher: str,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Execute a read-only Cypher query in the tenant's database.

        The query is executed inside an auto-committed read transaction
        (``AsyncSession.execute_read``).  Use this for all ``MATCH``
        queries that do not modify data.

        Args:
            ctx: Tenant context; determines the target database.
            cypher: The Cypher query string.
            params: Optional parameters.  Implementations inject
                ``tenant_id`` automatically.

        Returns:
            Sequence of result records as immutable mappings.

        Raises:
            InfraError: For any Neo4j driver or network failure
                (timeout 1 000 ms, 0 retries — fail fast, Pinecone fallback).
        """
        ...

    async def run_write(
        self,
        ctx: TenantContext,
        cypher: str,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Execute a write Cypher query in the tenant's database.

        The query is executed inside an auto-committed write transaction
        (``AsyncSession.execute_write``).  Suitable for simple,
        single-statement writes.  For multi-statement atomic operations
        use ``run_in_transaction``.

        Args:
            ctx: Tenant context; determines the target database.
            cypher: The Cypher query string.
            params: Optional parameters.  Implementations inject
                ``tenant_id`` automatically.

        Returns:
            Sequence of result records as immutable mappings.

        Raises:
            InfraError: For any Neo4j driver or network failure.
        """
        ...

    async def run_in_transaction(
        self,
        ctx: TenantContext,
        work: Callable[[Transaction], Awaitable[T]],
    ) -> T:
        """Execute *work* atomically inside a Neo4j write transaction.

        The driver retries *work* automatically on ``TransientError`` up to
        ``MAX_TRANSACTION_RETRY_TIME=5s`` (@docs/04-data-stores.md §2.5).

        Used for Stage B atomic-ish swap (Pinecone upsert + delete + Neo4j
        swap within one Neo4j transaction).

        Args:
            ctx: Tenant context; determines the target database.
            work: An async callable that receives a ``Transaction`` handle
                and returns a result of type ``T``.

        Returns:
            The value returned by *work*.

        Raises:
            InfraError: If the transaction fails after all driver retries.
        """
        ...
