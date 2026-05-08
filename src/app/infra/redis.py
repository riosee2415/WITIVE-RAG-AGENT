"""Redis adapter protocol — cache and invalidation epoch operations.

All keys must embed tenant or resource identifiers according to the naming
convention in @docs/04-data-stores.md §4.1.  Implementations must validate
key prefixes before executing commands and raise ``InfraError`` on violations.

No external ``redis`` / ``aioredis`` SDK is imported here.

Key naming rules (from @docs/04-data-stores.md §4.1):
- ``epoch:{tenant_id}``            — invalidation counter (no TTL)
- ``rag:q1:{tenant_id}:...``       — 1st-stage query cache
- ``rag:q2:{tenant_id}:...``       — 2nd-stage query cache
- ``dup:{user_id}:{sha256}``       — duplicate-question counter
- ``meta:doc:{tenant_id}:{doc_id}``— document metadata cache
- ``meta:tenant:{tenant_id}``      — tenant metadata cache
- ``meta:user:{user_id}``          — user profile cache
- ``job:{job_id}``                 — pipeline job state cache (5 s TTL)

SCAN / KEYS operations are **forbidden** (@docs/04-data-stores.md §4.3).
All cache invalidation is done via ``INCR epoch:{tenant_id}`` or targeted
single-key ``delete`` calls.

References:
  @docs/04-data-stores.md §4 (Redis key naming, values, invalidation, timeout)
  @docs/08-resilience.md §5.1 (Redis timeout: 100 ms, 1 retry)
  @docs/12-coding-conventions.md §7.2 (Protocol for infra interfaces)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

__all__ = ["RedisAdapter", "RedisPipeline"]


@runtime_checkable
class RedisPipeline(Protocol):
    """Protocol for a Redis pipeline (command batch).

    Commands are queued with ``set``, ``delete``, and ``incr``; ``execute``
    sends them atomically (as a pipelined batch, not a MULTI/EXEC
    transaction unless the implementation uses one).

    Use ``RedisAdapter.pipeline()`` to obtain an instance.
    """

    def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_s: int | None = None,
    ) -> None:
        """Queue a SET command.

        Args:
            key: Redis key (must follow naming convention).
            value: Raw bytes to store.
            ttl_s: Optional expiry in seconds (``EX`` option).
        """
        ...

    def delete(self, key: str) -> None:
        """Queue a DEL command.

        Args:
            key: Redis key to delete.
        """
        ...

    def incr(self, key: str) -> None:
        """Queue an INCR command.

        Args:
            key: Redis key to increment (must be an integer-valued key).
        """
        ...

    async def execute(self) -> Sequence[Any]:
        """Flush all queued commands and return their results.

        Returns:
            Sequence of raw Redis reply values, one per queued command,
            in the order the commands were queued.

        Raises:
            InfraError: For any Redis/network failure.
        """
        ...


@runtime_checkable
class RedisAdapter(Protocol):
    """Async protocol for Redis cache and epoch-counter operations.

    **Key prefix invariant**: implementations must verify that every key
    conforms to the naming convention in @docs/04-data-stores.md §4.1.
    Keys that do not match any recognised prefix pattern must be rejected
    with ``InfraError`` rather than silently executed.

    **SCAN / KEYS are forbidden** — all invalidation is done via
    ``INCR epoch:{tenant_id}`` or targeted single-key ``delete``.

    **Timeout**: 100 ms per command (@docs/08-resilience.md §5.1).
    **Retry**: 1 attempt (50 ms backoff) — Redis recovers quickly.
    On failure: cache miss / degraded mode (service continues).
    """

    async def get(self, key: str) -> bytes | None:
        """Return the value stored at *key*, or ``None`` if absent.

        Args:
            key: Redis key (must follow naming convention).

        Returns:
            Raw bytes if the key exists, ``None`` on a cache miss.

        Raises:
            InfraError: For any Redis/network failure (timeout 100 ms).
        """
        ...

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_s: int | None = None,
    ) -> None:
        """Store *value* at *key* with an optional TTL.

        Args:
            key: Redis key (must follow naming convention).
            value: Raw bytes to store.
            ttl_s: Optional expiry in seconds.  ``None`` means no expiry
                (e.g. ``epoch:{tenant_id}`` counters are persistent).

        Raises:
            InfraError: For any Redis/network failure.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete the value at *key* (no-op if absent).

        Used for targeted cache invalidation
        (@docs/04-data-stores.md §4.3).

        Args:
            key: Redis key to delete.

        Raises:
            InfraError: For any Redis/network failure.
        """
        ...

    async def incr(self, key: str) -> int:
        """Atomically increment the integer counter at *key* and return it.

        Used exclusively for epoch invalidation:
        ``INCR epoch:{tenant_id}`` after each document change.
        The key is created with value 1 if it does not exist.

        Args:
            key: Redis key (must start with ``epoch:``).

        Returns:
            New integer value after increment.

        Raises:
            InfraError: For any Redis/network failure.
        """
        ...

    async def pipeline(self) -> RedisPipeline:
        """Return a new pipeline instance for batching commands.

        The returned pipeline is **not** thread-safe; use one pipeline per
        coroutine.

        Returns:
            A fresh ``RedisPipeline`` ready for command queuing.

        Raises:
            InfraError: If the Redis connection is unavailable.
        """
        ...
