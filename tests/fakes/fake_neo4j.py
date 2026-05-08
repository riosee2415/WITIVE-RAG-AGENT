"""In-memory fake Neo4j adapter for unit tests — no external SDK required.

Implements ``Neo4jAdapter`` and ``Transaction`` Protocols using simple dict-based
storage.  Does NOT attempt to parse or execute real Cypher queries.

Simplification strategy (docs §2 graph moddelling out of scope for unit tests):
  1. ``run_read`` / ``run_write`` consult a stub registry first.  If a
     registered pattern matches the query string (``str.startswith`` or
     ``str.__contains__``), the stub response is returned.
  2. A small set of named helper methods (``upsert_document``, ``upsert_version``,
     ``upsert_chunk``, ``link_version``, ``swap_version``, ``get_chunks``,
     ``get_versions``) expose typed dict-level CRUD for the test scenarios
     required by @docs/04-data-stores.md §2.2 (MERGE idempotency, SUPERSEDES,
     is_current toggle).
  3. ``run_in_transaction`` wraps a ``FakeTransaction`` and executes ``work``
     synchronously within the same event loop (no true Neo4j retry).

References:
  @docs/04-data-stores.md §2 (Neo4j schema, naming)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeVar

from app.domain.tenant import TenantContext
from app.infra.neo4j import Transaction

__all__ = ["FakeNeo4j"]

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Fake Transaction
# ---------------------------------------------------------------------------


class _FakeTransaction:
    """Fake ``Transaction`` for use inside ``run_in_transaction``."""

    def __init__(self, store: dict[str, Any]) -> None:
        """Initialise the fake transaction with shared mutable *store*.

        Args:
            store: Reference to the parent ``FakeNeo4j`` store dict.
        """
        self._store = store
        self._calls: list[tuple[str, Mapping[str, Any] | None]] = []

    async def run(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Record the call and return an empty result sequence.

        Args:
            cypher: The Cypher query string (recorded for assertion).
            params: Optional parameters (recorded for assertion).

        Returns:
            Empty sequence (all real results should use helper methods).
        """
        self._calls.append((cypher, params))
        return []

    @property
    def calls(self) -> list[tuple[str, Mapping[str, Any] | None]]:
        """Return all (cypher, params) pairs recorded during the transaction."""
        return list(self._calls)


# ---------------------------------------------------------------------------
# FakeNeo4j
# ---------------------------------------------------------------------------


class FakeNeo4j:
    """In-memory fake implementation of ``Neo4jAdapter``.

    Internal storage layout::

        _docs: dict[str, dict]       — doc_id → document props
        _versions: dict[str, dict]   — version_id → version props
        _chunks: dict[str, dict]     — chunk_id → chunk props
        _doc_versions: dict[str, list[str]]   — doc_id → [version_id, ...]
        _version_chunks: dict[str, list[str]] — version_id → [chunk_id, ...]
        _supersedes: dict[str, str]  — newer_version_id → older_version_id

    Tenant isolation: ``_db_name(ctx)`` mirrors the real
    ``tenant_{tenant_id.hex}`` mapping but is used only as a namespace key in
    the internal store dict.  Each tenant gets its own sub-dict.

    Thread-safety: not guaranteed — use one instance per test coroutine.
    """

    def __init__(self) -> None:
        """Initialise empty per-tenant database stores."""
        # db_name → namespace dict
        self._databases: dict[str, dict[str, Any]] = {}
        # Stub registry: list of (pattern, response_list)
        self._stubs: list[tuple[str, list[Mapping[str, Any]]]] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _db_name(ctx: TenantContext) -> str:
        """Derive the logical database name from tenant context.

        Mirrors the production convention ``tenant_{tenant_id.hex}``.

        Args:
            ctx: Tenant context.

        Returns:
            Database name string, e.g. ``"tenant_abc123..."``.
        """
        return f"tenant_{ctx.tenant_id.hex}"

    def _ns(self, ctx: TenantContext) -> dict[str, Any]:
        """Return (or create) the namespace dict for *ctx*'s tenant."""
        db = self._db_name(ctx)
        if db not in self._databases:
            self._databases[db] = {
                "docs": {},
                "versions": {},
                "chunks": {},
                "doc_versions": {},
                "version_chunks": {},
                "supersedes": {},
            }
        return self._databases[db]

    def _lookup_stub(self, cypher: str) -> list[Mapping[str, Any]] | None:
        """Check stub registry for a matching Cypher pattern.

        Uses ``str.startswith`` first, then ``__contains__`` as fallback.

        Args:
            cypher: The Cypher query string to match.

        Returns:
            Registered stub response, or ``None`` if no match.
        """
        for pattern, response in self._stubs:
            if cypher.startswith(pattern) or pattern in cypher:
                return list(response)
        return None

    # ------------------------------------------------------------------
    # Stub registration (test helper)
    # ------------------------------------------------------------------

    def stub_response(
        self,
        cypher_pattern: str,
        response: list[Mapping[str, Any]],
    ) -> None:
        """Register a stub response for queries matching *cypher_pattern*.

        If multiple stubs match, the first registered wins.

        Args:
            cypher_pattern: A string that must appear in the Cypher query
                (uses ``startswith`` first, then ``in``).
            response: The result sequence to return when matched.
        """
        self._stubs.append((cypher_pattern, list(response)))

    # ------------------------------------------------------------------
    # Named helper methods (typed dict-level CRUD)
    # ------------------------------------------------------------------

    def upsert_document(
        self,
        ctx: TenantContext,
        doc_id: str,
        props: dict[str, Any],
    ) -> None:
        """MERGE-style insert/update a Document node.

        Idempotent: subsequent calls with the same *doc_id* merge *props*
        into the existing record (ON MATCH semantics).

        Args:
            ctx: Tenant context.
            doc_id: Document identifier.
            props: Document properties dict.
        """
        ns = self._ns(ctx)
        existing: dict[str, Any] = ns["docs"].get(doc_id, {})
        existing.update(props)
        existing["doc_id"] = doc_id
        ns["docs"][doc_id] = existing

    def upsert_version(
        self,
        ctx: TenantContext,
        doc_id: str,
        version_id: str,
        props: dict[str, Any],
        *,
        prev_version_id: str | None = None,
    ) -> None:
        """MERGE-style insert/update a Version node, optionally linking SUPERSEDES.

        Sets ``is_current=False`` on create (staging behaviour from docs §2.5).

        Args:
            ctx: Tenant context.
            doc_id: Parent document ID.
            version_id: Version identifier.
            props: Version properties dict.
            prev_version_id: If provided, a ``SUPERSEDES`` edge is created
                from *version_id* → *prev_version_id*.
        """
        ns = self._ns(ctx)
        existing: dict[str, Any] = ns["versions"].get(version_id, {})
        existing.update(props)
        existing["version_id"] = version_id
        existing.setdefault("is_current", False)
        ns["versions"][version_id] = existing
        # HAS_VERSION relationship
        ns["doc_versions"].setdefault(doc_id, [])
        if version_id not in ns["doc_versions"][doc_id]:
            ns["doc_versions"][doc_id].append(version_id)
        # SUPERSEDES relationship
        if prev_version_id is not None:
            ns["supersedes"][version_id] = prev_version_id

    def upsert_chunk(
        self,
        ctx: TenantContext,
        version_id: str,
        chunk_id: str,
        props: dict[str, Any],
    ) -> None:
        """MERGE-style insert/update a Chunk node under *version_id*.

        Sets ``staging=True`` on create/match (from docs §2.5).

        Args:
            ctx: Tenant context.
            version_id: Parent version ID.
            chunk_id: Chunk identifier.
            props: Chunk properties dict.
        """
        ns = self._ns(ctx)
        existing: dict[str, Any] = ns["chunks"].get(chunk_id, {})
        existing.update(props)
        existing["chunk_id"] = chunk_id
        existing["staging"] = True
        ns["chunks"][chunk_id] = existing
        ns["version_chunks"].setdefault(version_id, [])
        if chunk_id not in ns["version_chunks"][version_id]:
            ns["version_chunks"][version_id].append(chunk_id)

    def swap_version(
        self,
        ctx: TenantContext,
        doc_id: str,
        new_version_id: str,
    ) -> None:
        """Perform Stage B swap: set new version ``is_current=True``, old to ``False``.

        Also sets all chunks of *new_version_id* to ``staging=False``.

        Args:
            ctx: Tenant context.
            doc_id: Parent document ID.
            new_version_id: The version to promote to current.
        """
        ns = self._ns(ctx)
        # Demote all existing current versions for this doc
        for vid in ns["doc_versions"].get(doc_id, []):
            if vid != new_version_id and ns["versions"].get(vid, {}).get("is_current"):
                ns["versions"][vid]["is_current"] = False
        # Promote new version
        if new_version_id in ns["versions"]:
            ns["versions"][new_version_id]["is_current"] = True
        # Unstage chunks
        for chunk_id in ns["version_chunks"].get(new_version_id, []):
            if chunk_id in ns["chunks"]:
                ns["chunks"][chunk_id]["staging"] = False

    def get_versions(
        self,
        ctx: TenantContext,
        doc_id: str,
    ) -> list[dict[str, Any]]:
        """Return all Version nodes associated with *doc_id*, with SUPERSEDES info.

        Each result dict has an extra ``"supersedes"`` key containing the
        older version_id (or ``None``).

        Args:
            ctx: Tenant context.
            doc_id: Document ID to query.

        Returns:
            List of version dicts with ``"supersedes"`` field injected.
        """
        ns = self._ns(ctx)
        results: list[dict[str, Any]] = []
        for vid in ns["doc_versions"].get(doc_id, []):
            v = dict(ns["versions"].get(vid, {}))
            v["supersedes"] = ns["supersedes"].get(vid)
            results.append(v)
        return results

    def get_chunks(
        self,
        ctx: TenantContext,
        version_id: str,
    ) -> list[dict[str, Any]]:
        """Return all Chunk nodes for *version_id*.

        Args:
            ctx: Tenant context.
            version_id: Version ID to query.

        Returns:
            List of chunk dicts.
        """
        ns = self._ns(ctx)
        return [
            dict(ns["chunks"][cid])
            for cid in ns["version_chunks"].get(version_id, [])
            if cid in ns["chunks"]
        ]

    # ------------------------------------------------------------------
    # Neo4jAdapter interface
    # ------------------------------------------------------------------

    async def run_read(
        self,
        ctx: TenantContext,  # noqa: ARG002
        cypher: str,
        params: Mapping[str, Any] | None = None,  # noqa: ARG002
    ) -> Sequence[Mapping[str, Any]]:
        """Execute a read query — returns stub response if registered, else ``[]``.

        Args:
            ctx: Tenant context.
            cypher: Cypher query string.
            params: Optional parameters.

        Returns:
            Stub response if a matching pattern was registered, else empty list.
        """
        stub = self._lookup_stub(cypher)
        if stub is not None:
            return stub
        return []

    async def run_write(
        self,
        ctx: TenantContext,  # noqa: ARG002
        cypher: str,
        params: Mapping[str, Any] | None = None,  # noqa: ARG002
    ) -> Sequence[Mapping[str, Any]]:
        """Execute a write query — returns stub response if registered, else ``[]``.

        Args:
            ctx: Tenant context.
            cypher: Cypher query string.
            params: Optional parameters.

        Returns:
            Stub response if a matching pattern was registered, else empty list.
        """
        stub = self._lookup_stub(cypher)
        if stub is not None:
            return stub
        return []

    async def run_in_transaction(
        self,
        ctx: TenantContext,
        work: Callable[[Transaction], Awaitable[T]],
    ) -> T:
        """Execute *work* with a ``FakeTransaction`` (no real retry loop).

        Args:
            ctx: Tenant context.
            work: Async callable that receives a ``Transaction`` handle.

        Returns:
            Whatever *work* returns.
        """
        tx = _FakeTransaction(self._ns(ctx))
        return await work(tx)
