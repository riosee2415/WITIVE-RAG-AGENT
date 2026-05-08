"""Unit tests for FakeNeo4j — Document/Version/Chunk MERGE idempotency, SUPERSEDES.

References:
  @docs/04-data-stores.md §2 (Neo4j schema, naming, staging/live swap)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.access import Role
from app.domain.tenant import TenantContext
from app.infra.neo4j import Transaction
from tests.fakes.fake_neo4j import FakeNeo4j

_TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _ctx(tenant_id: uuid.UUID = _TENANT) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=_USER,
        role=Role.COMPANY_ADMIN,
        departments=(),
        level=None,
        hire_date=None,
        request_id="req-neo4j-test",
    )


@pytest.fixture()
def neo4j() -> FakeNeo4j:
    """Return a fresh FakeNeo4j instance."""
    return FakeNeo4j()


# ---------------------------------------------------------------------------
# upsert_document — MERGE idempotency
# ---------------------------------------------------------------------------


class TestUpsertDocument:
    def test_upsert_document_creates_new(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "취업규칙", "archived": False})
        ns = neo4j._ns(ctx)
        assert ns["docs"]["doc-1"]["doc_name"] == "취업규칙"

    def test_upsert_document_merges_on_match(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "취업규칙", "archived": False})
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "취업규칙 개정판"})
        ns = neo4j._ns(ctx)
        assert ns["docs"]["doc-1"]["doc_name"] == "취업규칙 개정판"
        assert ns["docs"]["doc-1"]["archived"] is False  # Previous field preserved

    def test_upsert_document_preserves_doc_id(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "Test"})
        ns = neo4j._ns(ctx)
        assert ns["docs"]["doc-1"]["doc_id"] == "doc-1"


# ---------------------------------------------------------------------------
# upsert_version — staging, SUPERSEDES
# ---------------------------------------------------------------------------


class TestUpsertVersion:
    def test_upsert_version_defaults_is_current_false(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "Doc"})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        ns = neo4j._ns(ctx)
        assert ns["versions"]["ver-1"]["is_current"] is False

    def test_upsert_version_links_to_doc(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "Doc"})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        ns = neo4j._ns(ctx)
        assert "ver-1" in ns["doc_versions"]["doc-1"]

    def test_upsert_version_idempotent(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0", "extra": True})
        ns = neo4j._ns(ctx)
        # Version_id appears only once in the list
        assert ns["doc_versions"]["doc-1"].count("ver-1") == 1
        assert ns["versions"]["ver-1"]["extra"] is True

    def test_upsert_version_creates_supersedes_edge(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        neo4j.upsert_version(ctx, "doc-1", "ver-2", {"version": "2.0"}, prev_version_id="ver-1")
        ns = neo4j._ns(ctx)
        assert ns["supersedes"]["ver-2"] == "ver-1"

    def test_two_version_chain_via_get_versions(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {"doc_name": "취업규칙"})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        neo4j.upsert_version(ctx, "doc-1", "ver-2", {"version": "2.1"}, prev_version_id="ver-1")
        versions = neo4j.get_versions(ctx, "doc-1")
        v2 = next((v for v in versions if v["version_id"] == "ver-2"), None)
        assert v2 is not None
        assert v2["supersedes"] == "ver-1"

    def test_root_version_has_no_supersedes(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        versions = neo4j.get_versions(ctx, "doc-1")
        v1 = next((v for v in versions if v["version_id"] == "ver-1"), None)
        assert v1 is not None
        assert v1["supersedes"] is None


# ---------------------------------------------------------------------------
# upsert_chunk — staging flag
# ---------------------------------------------------------------------------


class TestUpsertChunk:
    def test_upsert_chunk_sets_staging_true(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        neo4j.upsert_chunk(ctx, "ver-1", "chunk-1", {"text": "Hello", "page": 1})
        chunks = neo4j.get_chunks(ctx, "ver-1")
        assert len(chunks) == 1
        assert chunks[0]["staging"] is True

    def test_upsert_chunk_idempotent(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {})
        neo4j.upsert_chunk(ctx, "ver-1", "chunk-1", {"text": "Hello"})
        neo4j.upsert_chunk(ctx, "ver-1", "chunk-1", {"text": "World"})
        chunks = neo4j.get_chunks(ctx, "ver-1")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "World"


# ---------------------------------------------------------------------------
# swap_version — is_current toggle
# ---------------------------------------------------------------------------


class TestSwapVersion:
    def test_swap_promotes_new_version_is_current(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        neo4j.swap_version(ctx, "doc-1", "ver-1")
        ns = neo4j._ns(ctx)
        assert ns["versions"]["ver-1"]["is_current"] is True

    def test_swap_demotes_old_current_version(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {"version": "1.0"})
        neo4j.swap_version(ctx, "doc-1", "ver-1")
        neo4j.upsert_version(ctx, "doc-1", "ver-2", {"version": "2.0"})
        neo4j.swap_version(ctx, "doc-1", "ver-2")
        ns = neo4j._ns(ctx)
        assert ns["versions"]["ver-1"]["is_current"] is False
        assert ns["versions"]["ver-2"]["is_current"] is True

    def test_swap_unstages_chunks(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.upsert_document(ctx, "doc-1", {})
        neo4j.upsert_version(ctx, "doc-1", "ver-1", {})
        neo4j.upsert_chunk(ctx, "ver-1", "chunk-1", {"text": "Chunk text"})
        neo4j.swap_version(ctx, "doc-1", "ver-1")
        chunks = neo4j.get_chunks(ctx, "ver-1")
        assert chunks[0]["staging"] is False


# ---------------------------------------------------------------------------
# run_read / run_write — stub registry
# ---------------------------------------------------------------------------


class TestStubRegistry:
    async def test_stub_response_matched_by_startswith(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.stub_response("MATCH (c:Chunk)", [{"c": {"chunk_id": "c1"}}])
        result = await neo4j.run_read(ctx, "MATCH (c:Chunk) WHERE c.chunk_id IN $ids")
        assert len(result) == 1
        assert result[0]["c"]["chunk_id"] == "c1"

    async def test_stub_response_matched_by_contains(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.stub_response("HAS_VERSION", [{"count": 5}])
        result = await neo4j.run_read(ctx, "MATCH (d)-[:HAS_VERSION]->(v) RETURN count(*)")
        assert result[0]["count"] == 5

    async def test_no_stub_returns_empty(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        result = await neo4j.run_read(ctx, "MATCH (n) RETURN n")
        assert result == []

    async def test_run_write_respects_stub(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        neo4j.stub_response("MERGE (d:Document", [{"merged": True}])
        result = await neo4j.run_write(ctx, "MERGE (d:Document {doc_id: $id})")
        assert result[0]["merged"] is True


# ---------------------------------------------------------------------------
# run_in_transaction
# ---------------------------------------------------------------------------


class TestRunInTransaction:
    async def test_transaction_work_is_called(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        calls: list[str] = []

        async def work(tx: Transaction) -> str:
            await tx.run("MERGE (d:Document {doc_id: $id})", {"id": "doc-1"})
            calls.append("executed")
            return "ok"

        result = await neo4j.run_in_transaction(ctx, work)
        assert result == "ok"
        assert calls == ["executed"]

    async def test_transaction_run_records_calls(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        recorded: list[tuple] = []

        async def work(tx: Transaction) -> None:
            await tx.run("MERGE (v:Version {version_id: $vid})", {"vid": "v1"})
            # Cast to the fake to inspect recorded calls
            from tests.fakes.fake_neo4j import _FakeTransaction

            assert isinstance(tx, _FakeTransaction)
            recorded.extend(tx.calls)

        await neo4j.run_in_transaction(ctx, work)
        assert len(recorded) == 1
        assert recorded[0][0] == "MERGE (v:Version {version_id: $vid})"

    async def test_transaction_isinstance_transaction_protocol(self, neo4j: FakeNeo4j) -> None:
        ctx = _ctx()
        seen: list[bool] = []

        async def work(tx: Transaction) -> None:
            seen.append(isinstance(tx, Transaction))

        await neo4j.run_in_transaction(ctx, work)
        assert seen == [True]
