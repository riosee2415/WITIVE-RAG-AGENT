"""Unit tests for FakeEmbeddings — deterministic output, dimension, batch consistency.

References:
  @docs/04-data-stores.md §1.1 (dimension = 1 536)
  @docs/05-llm-bedrock.md §5 (Titan v2)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import math
import uuid

import pytest

from app.domain.access import Role
from app.domain.tenant import TenantContext
from tests.fakes.fake_embeddings import DIMENSION, FakeEmbeddings

_TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _ctx() -> TenantContext:
    return TenantContext(
        tenant_id=_TENANT,
        user_id=_USER,
        role=Role.COMPANY_USER,
        departments=(),
        level=None,
        hire_date=None,
        request_id="req-emb-test",
    )


@pytest.fixture()
def emb() -> FakeEmbeddings:
    """Return a shared FakeEmbeddings instance (stateless)."""
    return FakeEmbeddings()


# ---------------------------------------------------------------------------
# Dimension
# ---------------------------------------------------------------------------


class TestDimension:
    def test_dimension_constant_is_1536(self) -> None:
        assert DIMENSION == 1536

    def test_instance_dimension_constant_is_1536(self, emb: FakeEmbeddings) -> None:
        assert emb.dimension == 1536

    async def test_embed_single_returns_1536_floats(self, emb: FakeEmbeddings) -> None:
        vec = await emb.embed_single(_ctx(), "test text")
        assert len(vec) == 1536

    async def test_embed_batch_each_result_is_1536_floats(self, emb: FakeEmbeddings) -> None:
        texts = ["text one", "text two", "text three"]
        results = await emb.embed_batch(_ctx(), texts)
        assert len(results) == 3
        for vec in results:
            assert len(vec) == 1536


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    async def test_same_text_same_vector_single(self, emb: FakeEmbeddings) -> None:
        vec1 = await emb.embed_single(_ctx(), "연차휴가 규정")
        vec2 = await emb.embed_single(_ctx(), "연차휴가 규정")
        assert vec1 == vec2

    async def test_different_text_different_vector(self, emb: FakeEmbeddings) -> None:
        vec1 = await emb.embed_single(_ctx(), "연차휴가 규정")
        vec2 = await emb.embed_single(_ctx(), "출장 규정")
        assert vec1 != vec2

    async def test_batch_same_texts_same_vectors(self, emb: FakeEmbeddings) -> None:
        texts = ["연차휴가", "출장비", "취업규칙"]
        results1 = await emb.embed_batch(_ctx(), texts)
        results2 = await emb.embed_batch(_ctx(), texts)
        assert list(results1) == list(results2)

    async def test_batch_order_preserved(self, emb: FakeEmbeddings) -> None:
        texts = ["first", "second", "third"]
        results = await emb.embed_batch(_ctx(), texts)
        single_first = await emb.embed_single(_ctx(), "first")
        single_second = await emb.embed_single(_ctx(), "second")
        single_third = await emb.embed_single(_ctx(), "third")
        assert results[0] == single_first
        assert results[1] == single_second
        assert results[2] == single_third


# ---------------------------------------------------------------------------
# Unit norm
# ---------------------------------------------------------------------------


class TestUnitNorm:
    async def test_embed_single_has_unit_l2_norm(self, emb: FakeEmbeddings) -> None:
        vec = await emb.embed_single(_ctx(), "some text for norm check")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    async def test_embed_batch_all_unit_norm(self, emb: FakeEmbeddings) -> None:
        texts = [f"text number {i}" for i in range(5)]
        results = await emb.embed_batch(_ctx(), texts)
        for vec in results:
            norm = math.sqrt(sum(x * x for x in vec))
            assert abs(norm - 1.0) < 1e-6, f"Norm {norm} is not close to 1.0"


# ---------------------------------------------------------------------------
# Batch and single consistency
# ---------------------------------------------------------------------------


class TestBatchSingleConsistency:
    async def test_single_item_batch_equals_embed_single(self, emb: FakeEmbeddings) -> None:
        text = "consistency check"
        batch_result = await emb.embed_batch(_ctx(), [text])
        single_result = await emb.embed_single(_ctx(), text)
        assert batch_result[0] == single_result

    async def test_empty_batch_returns_empty(self, emb: FakeEmbeddings) -> None:
        results = await emb.embed_batch(_ctx(), [])
        assert list(results) == []


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    async def test_embed_single_returns_tuple(self, emb: FakeEmbeddings) -> None:
        vec = await emb.embed_single(_ctx(), "type check")
        assert isinstance(vec, tuple)

    async def test_embed_batch_returns_sequence_of_tuples(self, emb: FakeEmbeddings) -> None:
        results = await emb.embed_batch(_ctx(), ["a", "b"])
        for vec in results:
            assert isinstance(vec, tuple)
