"""In-memory fake Redis adapter for unit tests — no external SDK required.

Implements ``RedisAdapter`` and ``RedisPipeline`` (``@runtime_checkable``
Protocols) using a plain dict store with optional TTL support.

Key validation: every key is checked against the naming convention defined in
@docs/04-data-stores.md §4.1.  Invalid keys raise ``InfraError("INVALID_KEY")``.

Time can be advanced for TTL testing via ``advance_time(seconds=N)`` on
an instance of ``FakeRedis``.

References:
  @docs/04-data-stores.md §4 (Redis key naming, TTL, invalidation)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import re
import time as _time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.infra._base import InfraError
from app.infra.redis import RedisPipeline

__all__ = ["FakeRedis"]

# ---------------------------------------------------------------------------
# Key naming convention (docs §4.1)
# ---------------------------------------------------------------------------

# Recognised key prefix patterns (pre-compiled for speed).
_VALID_KEY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^epoch:[^:]+$"),  # epoch:{tenant_id}
    re.compile(r"^rag:q[12]:[^:]+:.+$"),  # rag:q1/q2:{tenant_id}:...
    re.compile(r"^dup:[^:]+:[^:]+$"),  # dup:{user_id}:{sha256}
    re.compile(r"^meta:doc:[^:]+:[^:]+$"),  # meta:doc:{tenant_id}:{doc_id}
    re.compile(r"^meta:tenant:[^:]+$"),  # meta:tenant:{tenant_id}
    re.compile(r"^meta:user:[^:]+$"),  # meta:user:{user_id}
    re.compile(r"^job:[^:]+$"),  # job:{job_id}
]


def _validate_key_format(key: str) -> None:
    """Raise ``InfraError`` if *key* does not match any recognised prefix pattern.

    Args:
        key: The Redis key to validate.

    Raises:
        InfraError: With code ``"INVALID_KEY"`` if the key does not match any
            pattern defined in @docs/04-data-stores.md §4.1.
    """
    if any(p.match(key) for p in _VALID_KEY_PATTERNS):
        return
    raise InfraError(
        "INVALID_KEY",
        f"Key {key!r} does not match any recognised Redis naming pattern "
        "(see @docs/04-data-stores.md §4.1)",
    )


# ---------------------------------------------------------------------------
# Internal storage
# ---------------------------------------------------------------------------


@dataclass
class _Entry:
    """A single stored Redis value with optional expiry timestamp."""

    value: bytes
    expires_at: float | None = None  # monotonic timestamp, None = no TTL


# ---------------------------------------------------------------------------
# Fake pipeline
# ---------------------------------------------------------------------------

_PipelineCommand = tuple[str, tuple[Any, ...], dict[str, Any]]


class _FakeRedisPipeline:
    """In-memory Redis pipeline that accumulates commands and executes them atomically."""

    def __init__(self, store: dict[str, _Entry], clock: _FakeClock) -> None:
        """Initialise a pipeline bound to *store* and *clock*.

        Args:
            store: Shared mutable key-value store from the parent ``FakeRedis``.
            clock: Mockable clock for TTL computation.
        """
        self._store = store
        self._clock = clock
        self._commands: list[_PipelineCommand] = []

    def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_s: int | None = None,
    ) -> None:
        """Queue a SET command.

        Args:
            key: Redis key.
            value: Raw bytes to store.
            ttl_s: Optional TTL in seconds.
        """
        _validate_key_format(key)
        self._commands.append(("set", (key, value), {"ttl_s": ttl_s}))

    def delete(self, key: str) -> None:
        """Queue a DEL command.

        Args:
            key: Redis key to delete.
        """
        _validate_key_format(key)
        self._commands.append(("delete", (key,), {}))

    def incr(self, key: str) -> None:
        """Queue an INCR command.

        Args:
            key: Redis key to increment.
        """
        _validate_key_format(key)
        self._commands.append(("incr", (key,), {}))

    async def execute(self) -> Sequence[Any]:
        """Execute all queued commands and return their results.

        Returns:
            Sequence of results: ``None`` for SET/DEL, ``int`` for INCR.
        """
        results: list[Any] = []
        for cmd, args, kwargs in self._commands:
            if cmd == "set":
                key, value = args
                ttl_s: int | None = kwargs.get("ttl_s")
                expires_at = self._clock.now() + ttl_s if ttl_s is not None else None
                self._store[key] = _Entry(value=value, expires_at=expires_at)
                results.append(None)
            elif cmd == "delete":
                (key,) = args
                self._store.pop(key, None)
                results.append(None)
            elif cmd == "incr":
                (key,) = args
                entry = self._store.get(key)
                current = int(entry.value) if entry else 0
                new_val = current + 1
                expires_at = entry.expires_at if entry else None
                self._store[key] = _Entry(value=str(new_val).encode(), expires_at=expires_at)
                results.append(new_val)
        self._commands.clear()
        return results


# ---------------------------------------------------------------------------
# Mockable clock
# ---------------------------------------------------------------------------


class _FakeClock:
    """Mockable monotonic clock for TTL tests."""

    def __init__(self) -> None:
        """Initialise the clock at the current real monotonic time."""
        self._offset: float = 0.0

    def now(self) -> float:
        """Return the current (possibly advanced) monotonic time."""
        return _time.monotonic() + self._offset

    def advance(self, seconds: float) -> None:
        """Advance the clock by *seconds*.

        Args:
            seconds: Number of seconds to add to the internal offset.
        """
        self._offset += seconds


# ---------------------------------------------------------------------------
# FakeRedis
# ---------------------------------------------------------------------------


@dataclass
class FakeRedis:
    """In-memory fake implementation of ``RedisAdapter``.

    Thread-safety: not guaranteed — use one instance per test coroutine.

    Attributes:
        _store: Internal key-value store.
        _clock: Mockable clock used for TTL expiry.
    """

    _store: dict[str, _Entry] = field(default_factory=dict)
    _clock: _FakeClock = field(default_factory=_FakeClock)

    def advance_time(self, seconds: float) -> None:
        """Advance the internal clock to simulate TTL expiry.

        Args:
            seconds: Number of seconds to advance.
        """
        self._clock.advance(seconds)

    def _is_alive(self, entry: _Entry) -> bool:
        """Return ``True`` if *entry* has not expired yet."""
        if entry.expires_at is None:
            return True
        return self._clock.now() < entry.expires_at

    async def get(self, key: str) -> bytes | None:
        """Return the value at *key*, or ``None`` if absent or expired.

        Args:
            key: Redis key (must match naming convention).

        Returns:
            Stored bytes, or ``None`` on miss / expiry.

        Raises:
            InfraError: If *key* does not match any recognised pattern.
        """
        _validate_key_format(key)
        entry = self._store.get(key)
        if entry is None or not self._is_alive(entry):
            if entry is not None:
                del self._store[key]
            return None
        return entry.value

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_s: int | None = None,
    ) -> None:
        """Store *value* at *key* with optional TTL.

        Args:
            key: Redis key.
            value: Raw bytes to store.
            ttl_s: Optional expiry in seconds.

        Raises:
            InfraError: If *key* does not match any recognised pattern.
        """
        _validate_key_format(key)
        expires_at = self._clock.now() + ttl_s if ttl_s is not None else None
        self._store[key] = _Entry(value=value, expires_at=expires_at)

    async def delete(self, key: str) -> None:
        """Delete the key (no-op if absent).

        Args:
            key: Redis key to delete.

        Raises:
            InfraError: If *key* does not match any recognised pattern.
        """
        _validate_key_format(key)
        self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        """Atomically increment the integer counter at *key* and return it.

        Creates the key at 1 if it does not exist.

        Args:
            key: Redis key (must start with ``epoch:``).

        Returns:
            New integer value after increment.

        Raises:
            InfraError: If *key* does not match any recognised pattern.
        """
        _validate_key_format(key)
        entry = self._store.get(key)
        current = int(entry.value) if entry and self._is_alive(entry) else 0
        new_val = current + 1
        expires_at = entry.expires_at if entry else None
        self._store[key] = _Entry(value=str(new_val).encode(), expires_at=expires_at)
        return new_val

    async def pipeline(self) -> RedisPipeline:
        """Return a new pipeline bound to this store and clock.

        Returns:
            A ``_FakeRedisPipeline`` instance ready for command queuing.
        """
        return _FakeRedisPipeline(self._store, self._clock)
