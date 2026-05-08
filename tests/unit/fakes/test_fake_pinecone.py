"""Unit tests for FakePinecone — query, filter DSL, cross-tenant, update_metadata.

References:
  @docs/04-data-stores.md §1 (Pinecone schema, query, upsert, update)
  @docs/07-multitenancy-and-access.md §2.2 (tenant enforcement)
"""

from __future__ import annotations

import math
import uuid

import pytest

from app.domain.access import Role
from app.domain.tenant import TenantContext
from app.infra._base import TenantMismatchError
from app.infra.pinecone import VectorRecord
from tests.fakes.fake_pinecone import FakePinecone

_TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_USER = uuid.UUID("cccccccc-0000-0000-0000-000000000003")


def _ctx(tenant_id: uuid.UUID = _TENANT_A) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=_USER,
        role=Role.COMPANY_USER,
        departments=("eng",),
        level=None,
        hire_date=None,
        request_id="req-pc-test",
    )


def _unit_vec(dim: int, *, value: float = 1.0) -> tuple[float, ...]:
    """Return a unit vector of *dim* dimensions set to *value* / sqrt(dim)."""
    v = value / math.sqrt(dim)
    return tuple(v for _ in range(dim))


def _make_record(
    vec_id: str,
    *,
    tenant_id: uuid.UUID = _TENANT_A,
    access_level: str = "COMPANY_WIDE",
    is_current: bool = True,
    archived: bool = False,
    index_state: str = "live",
    min_level_rank: int | None = None,
    allowed_departments: list[str] | None = None,
    dim: int = 4,
    value: float = 1.0,
) -> VectorRecord:
    """Build a test ``VectorRecord``."""
    return VectorRecord(
        id=vec_id,
        values=_unit_vec(dim, value=value),
        metadata={
            "tenant_id": str(tenant_id),
            "access_level": access_level,
            "is_current": is_current,
            "archived": archived,
            "index_state": index_state,
            "allowed_departments": allowed_departments or [],
            "min_level_rank": min_level_rank,
        },
    )


@pytest.fixture()
def pc() -> FakePinecone:
    """Return a fresh FakePinecone instance."""
    return FakePinecone()


# ---------------------------------------------------------------------------
# Upsert + Query basics
# ---------------------------------------------------------------------------


class TestUpsertAndQuery:
    async def test_upsert_then_query_returns_match(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        rec = _make_record("doc1:v1:0")
        await pc.upsert(ctx, [rec])
        query_vec = _unit_vec(4)
        results = await pc.query(ctx, query_vec, top_k=5, filter={})
        assert len(results) == 1
        assert results[0].id == "doc1:v1:0"

    async def test_query_returns_top_k_sorted_by_score_desc(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        # Two different vectors — we'll know which is closer to the query
        await pc.upsert(ctx, [_make_record("doc1", value=1.0)])
        # doc2 is a slightly different vector (pointing opposite direction partially)
        rec2 = VectorRecord(
            id="doc2",
            values=(0.0, 0.0, 0.0, 1.0),  # different direction
            metadata={"tenant_id": str(_TENANT_A)},
        )
        rec3 = VectorRecord(
            id="doc3",
            values=(1.0, 0.0, 0.0, 0.0),  # same direction as default query
            metadata={"tenant_id": str(_TENANT_A)},
        )
        await pc.upsert(ctx, [rec2, rec3])
        query = (1.0, 0.0, 0.0, 0.0)
        results = await pc.query(ctx, query, top_k=2, filter={})
        assert results[0].score >= results[1].score

    async def test_query_top_k_limits_results(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        records = [_make_record(f"doc{i}") for i in range(10)]
        await pc.upsert(ctx, records)
        results = await pc.query(ctx, _unit_vec(4), top_k=3, filter={})
        assert len(results) <= 3

    async def test_upsert_idempotent_same_id(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        rec1 = VectorRecord(
            id="doc1:v1:0",
            values=_unit_vec(4, value=1.0),
            metadata={"tenant_id": str(_TENANT_A), "index_state": "staging"},
        )
        rec2 = VectorRecord(
            id="doc1:v1:0",
            values=_unit_vec(4, value=1.0),
            metadata={"tenant_id": str(_TENANT_A), "index_state": "live"},
        )
        await pc.upsert(ctx, [rec1])
        await pc.upsert(ctx, [rec2])
        results = await pc.query(ctx, _unit_vec(4), top_k=5, filter={})
        assert len(results) == 1
        assert results[0].metadata["index_state"] == "live"


# ---------------------------------------------------------------------------
# Filter DSL
# ---------------------------------------------------------------------------


class TestFilterDsl:
    async def _seed(self, pc: FakePinecone, ctx: TenantContext) -> None:
        """Seed test vectors for filter tests."""
        records = [
            VectorRecord(
                id="wide",
                values=_unit_vec(4),
                metadata={
                    "tenant_id": str(_TENANT_A),
                    "access_level": "COMPANY_WIDE",
                    "archived": False,
                    "index_state": "live",
                    "is_current": True,
                    "min_level_rank": None,
                    "allowed_departments": [],
                },
            ),
            VectorRecord(
                id="dept-eng",
                values=_unit_vec(4),
                metadata={
                    "tenant_id": str(_TENANT_A),
                    "access_level": "DEPARTMENT",
                    "archived": False,
                    "index_state": "live",
                    "is_current": True,
                    "min_level_rank": None,
                    "allowed_departments": ["eng"],
                },
            ),
            VectorRecord(
                id="level4",
                values=_unit_vec(4),
                metadata={
                    "tenant_id": str(_TENANT_A),
                    "access_level": "LEVEL",
                    "archived": False,
                    "index_state": "live",
                    "is_current": True,
                    "min_level_rank": 4,
                    "allowed_departments": [],
                },
            ),
            VectorRecord(
                id="archived",
                values=_unit_vec(4),
                metadata={
                    "tenant_id": str(_TENANT_A),
                    "access_level": "COMPANY_WIDE",
                    "archived": True,
                    "index_state": "live",
                    "is_current": True,
                    "min_level_rank": None,
                    "allowed_departments": [],
                },
            ),
        ]
        await pc.upsert(ctx, records)

    async def test_filter_eq_access_level(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={"access_level": "COMPANY_WIDE", "archived": False},
        )
        ids = [r.id for r in results]
        assert "wide" in ids
        assert "dept-eng" not in ids

    async def test_filter_and_compound(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={"$and": [{"archived": False}, {"index_state": "live"}]},
        )
        ids = [r.id for r in results]
        assert "archived" not in ids
        assert "wide" in ids

    async def test_filter_or_compound(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={
                "$or": [
                    {"access_level": "COMPANY_WIDE"},
                    {"access_level": "LEVEL"},
                ]
            },
        )
        ids = [r.id for r in results]
        assert "wide" in ids
        assert "level4" in ids
        assert "dept-eng" not in ids

    async def test_filter_in_operator(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={"allowed_departments": {"$in": ["eng"]}},
        )
        ids = [r.id for r in results]
        assert "dept-eng" in ids
        assert "wide" not in ids

    async def test_filter_lte_operator(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        # User has level rank 5 → can access min_level_rank <= 5
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={"min_level_rank": {"$lte": 5}},
        )
        ids = [r.id for r in results]
        assert "level4" in ids

    async def test_filter_lte_excludes_higher_rank(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        # User has level rank 3 → cannot access min_level_rank 4
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={"min_level_rank": {"$lte": 3}},
        )
        ids = [r.id for r in results]
        assert "level4" not in ids

    async def test_filter_ne_operator(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        results = await pc.query(
            ctx,
            _unit_vec(4),
            top_k=10,
            filter={"access_level": {"$ne": "COMPANY_WIDE"}},
        )
        ids = [r.id for r in results]
        assert "wide" not in ids
        assert "archived" not in ids
        assert "dept-eng" in ids

    async def test_empty_filter_returns_all(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await self._seed(pc, ctx)
        results = await pc.query(ctx, _unit_vec(4), top_k=10, filter={})
        assert len(results) == 4


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_removes_vectors(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await pc.upsert(ctx, [_make_record("doc1"), _make_record("doc2")])
        await pc.delete(ctx, ["doc1"])
        results = await pc.query(ctx, _unit_vec(4), top_k=10, filter={})
        ids = [r.id for r in results]
        assert "doc1" not in ids
        assert "doc2" in ids

    async def test_delete_nonexistent_is_noop(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        await pc.delete(ctx, ["does-not-exist"])  # Must not raise


# ---------------------------------------------------------------------------
# update_metadata
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    async def test_update_metadata_merges(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        rec = VectorRecord(
            id="doc1:v1:0",
            values=_unit_vec(4),
            metadata={"tenant_id": str(_TENANT_A), "is_current": True},
        )
        await pc.upsert(ctx, [rec])
        await pc.update_metadata(
            ctx,
            "doc1:v1:0",
            {"tenant_id": str(_TENANT_A), "is_current": False},
        )
        results = await pc.query(ctx, _unit_vec(4), top_k=5, filter={})
        assert results[0].metadata["is_current"] is False

    async def test_update_metadata_preserves_other_fields(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        rec = VectorRecord(
            id="doc1:v1:0",
            values=_unit_vec(4),
            metadata={
                "tenant_id": str(_TENANT_A),
                "is_current": True,
                "doc_id": "d1",
            },
        )
        await pc.upsert(ctx, [rec])
        await pc.update_metadata(
            ctx,
            "doc1:v1:0",
            {"tenant_id": str(_TENANT_A), "is_current": False},
        )
        results = await pc.query(ctx, _unit_vec(4), top_k=5, filter={})
        assert results[0].metadata["doc_id"] == "d1"

    async def test_update_metadata_missing_vector_is_noop(self, pc: FakePinecone) -> None:
        ctx = _ctx()
        # Must not raise when vector_id doesn't exist
        await pc.update_metadata(
            ctx,
            "nonexistent",
            {"tenant_id": str(_TENANT_A)},
        )


# ---------------------------------------------------------------------------
# Cross-tenant enforcement
# ---------------------------------------------------------------------------


class TestCrossTenantEnforcement:
    async def test_upsert_wrong_metadata_tenant_raises_tenant_mismatch(
        self, pc: FakePinecone
    ) -> None:
        ctx_a = _ctx(_TENANT_A)
        # Metadata says tenant B but ctx is tenant A
        rec = VectorRecord(
            id="doc1:v1:0",
            values=_unit_vec(4),
            metadata={"tenant_id": str(_TENANT_B)},
        )
        with pytest.raises(TenantMismatchError) as exc_info:
            await pc.upsert(ctx_a, [rec])
        assert exc_info.value.resource == "pinecone_vector_metadata"

    async def test_upsert_batch_one_mismatch_aborts_all(self, pc: FakePinecone) -> None:
        ctx_a = _ctx(_TENANT_A)
        records = [
            VectorRecord(
                id="good",
                values=_unit_vec(4),
                metadata={"tenant_id": str(_TENANT_A)},
            ),
            VectorRecord(
                id="bad",
                values=_unit_vec(4),
                metadata={"tenant_id": str(_TENANT_B)},
            ),
        ]
        with pytest.raises(TenantMismatchError):
            await pc.upsert(ctx_a, records)
        # Neither should be stored
        results = await pc.query(ctx_a, _unit_vec(4), top_k=10, filter={})
        assert len(results) == 0

    async def test_update_metadata_wrong_tenant_raises_tenant_mismatch(
        self, pc: FakePinecone
    ) -> None:
        ctx_a = _ctx(_TENANT_A)
        # Seed a valid vector
        rec = VectorRecord(
            id="doc1",
            values=_unit_vec(4),
            metadata={"tenant_id": str(_TENANT_A)},
        )
        await pc.upsert(ctx_a, [rec])
        with pytest.raises(TenantMismatchError):
            await pc.update_metadata(ctx_a, "doc1", {"tenant_id": str(_TENANT_B)})

    async def test_query_only_returns_own_tenant_vectors(self, pc: FakePinecone) -> None:
        ctx_a = _ctx(_TENANT_A)
        ctx_b = _ctx(_TENANT_B)
        rec_a = VectorRecord(
            id="doc-a",
            values=_unit_vec(4),
            metadata={"tenant_id": str(_TENANT_A)},
        )
        rec_b = VectorRecord(
            id="doc-b",
            values=_unit_vec(4),
            metadata={"tenant_id": str(_TENANT_B)},
        )
        await pc.upsert(ctx_a, [rec_a])
        await pc.upsert(ctx_b, [rec_b])
        results_a = await pc.query(ctx_a, _unit_vec(4), top_k=10, filter={})
        ids_a = [r.id for r in results_a]
        assert "doc-a" in ids_a
        assert "doc-b" not in ids_a
