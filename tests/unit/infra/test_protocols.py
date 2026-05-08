"""Unit tests for app.infra protocol definitions and data classes.

Validates:
- ``InfraError`` / ``TenantMismatchError`` exception hierarchy
- All Protocol classes are ``@runtime_checkable``
- Frozen dataclasses (``ReceivedMessage``, ``VectorRecord``, ``QueryMatch``)
  are immutable and serialisable via ``dataclasses.asdict``
- ``S3Adapter.assert_tenant_key`` key-prefix enforcement helper
- Pinecone ``_assert_vector_tenant`` cross-tenant metadata guard
- ``__init__`` public surface (``__all__`` completeness)

No external SDK is imported; all fake adapters are defined inline.

Note: ``# type: ignore[override]`` is used on fake implementations that accept
``*args``/``**kwargs`` in place of the Protocol's concrete signature — the
runtime ``isinstance`` check is what matters for these tests, not strict
override matching.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from typing import Any
from uuid import UUID

import pytest

from app.domain.access import Role
from app.domain.tenant import TenantContext
from app.infra._base import InfraError, TenantMismatchError
from app.infra.embeddings import EmbeddingsAdapter
from app.infra.neo4j import Neo4jAdapter, Transaction
from app.infra.pinecone import (
    PineconeAdapter,
    QueryMatch,
    VectorRecord,
    _assert_vector_tenant,
)
from app.infra.redis import RedisAdapter, RedisPipeline
from app.infra.s3 import S3Adapter, assert_tenant_key
from app.infra.sqs import ReceivedMessage, SqsAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER_ID = UUID("bbbbbbbb-0000-0000-0000-000000000002")
_OTHER_TENANT_ID = UUID("cccccccc-0000-0000-0000-000000000003")


def _make_ctx(tenant_id: UUID = _TENANT_ID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=_USER_ID,
        role=Role.COMPANY_USER,
        departments=(),
        level=None,
        hire_date=None,
        request_id="req-test-001",
    )


# ---------------------------------------------------------------------------
# Minimal fake adapters (Protocol structural-subtype check only)
# Each fake has the required method names with the right arity.
# Unused-arg warnings are suppressed at the class level below.
# ---------------------------------------------------------------------------


class _FakeS3:
    async def put_object(self, *_: Any, **__: Any) -> str:  # type: ignore[override]
        return '"etag"'

    async def get_object(self, *_: Any, **__: Any) -> bytes:  # type: ignore[override]
        return b""

    async def head_object(self, *_: Any) -> dict[str, str]:  # type: ignore[override]
        return {}

    async def put_object_conditional(self, *_: Any, **__: Any) -> str:  # type: ignore[override]
        return '"etag"'

    async def list_objects(self, *_: Any, **__: Any) -> list[str]:  # type: ignore[override]
        return []

    async def copy_object(self, *_: Any) -> None:  # type: ignore[override]
        pass

    async def multipart_upload(self, *_: Any, **__: Any) -> str:  # type: ignore[override]
        return '"etag"'


class _FakeSqs:
    async def send_message(self, *_: Any, **__: Any) -> str:  # type: ignore[override]
        return "msg-id"

    async def receive_messages(self, *_: Any, **__: Any) -> list[ReceivedMessage]:  # type: ignore[override]
        return []

    async def delete_message(self, *_: Any) -> None:  # type: ignore[override]
        pass

    async def change_message_visibility(self, *_: Any) -> None:  # type: ignore[override]
        pass


class _FakePinecone:
    async def query(self, *_: Any, **__: Any) -> list[QueryMatch]:  # type: ignore[override]
        return []

    async def upsert(self, *_: Any) -> None:  # type: ignore[override]
        pass

    async def delete(self, *_: Any) -> None:  # type: ignore[override]
        pass

    async def update_metadata(self, *_: Any) -> None:  # type: ignore[override]
        pass


class _FakeNeo4j:
    async def run_read(self, *_: Any, **__: Any) -> list[dict[str, Any]]:  # type: ignore[override]
        return []

    async def run_write(self, *_: Any, **__: Any) -> list[dict[str, Any]]:  # type: ignore[override]
        return []

    async def run_in_transaction(self, *_: Any) -> None:  # type: ignore[override]
        pass


class _FakeTx:
    async def run(self, *_: Any, **__: Any) -> list[dict[str, Any]]:  # type: ignore[override]
        return []


class _FakeEmbeddings:
    async def embed_batch(self, *_: Any, **__: Any) -> list[tuple[float, ...]]:  # type: ignore[override]
        return []

    async def embed_single(self, *_: Any, **__: Any) -> tuple[float, ...]:  # type: ignore[override]
        return (0.0,) * 1536


class _FakePipeline:
    def set(self, *_: Any, **__: Any) -> None:  # type: ignore[override]
        pass

    def delete(self, *_: Any) -> None:  # type: ignore[override]
        pass

    def incr(self, *_: Any) -> None:  # type: ignore[override]
        pass

    async def execute(self) -> list[Any]:
        return []


class _FakeRedis:
    async def get(self, *_: Any) -> bytes | None:  # type: ignore[override]
        return None

    async def set(self, *_: Any, **__: Any) -> None:  # type: ignore[override]
        pass

    async def delete(self, *_: Any) -> None:  # type: ignore[override]
        pass

    async def incr(self, *_: Any) -> int:  # type: ignore[override]
        return 1

    async def pipeline(self) -> _FakePipeline:
        return _FakePipeline()


# ---------------------------------------------------------------------------
# 1. InfraError hierarchy
# ---------------------------------------------------------------------------


class TestInfraErrorHierarchy:
    def test_infra_error_is_exception(self) -> None:
        err = InfraError(code="TEST_CODE", message="something went wrong")
        assert isinstance(err, Exception)

    def test_infra_error_stores_code_and_message(self) -> None:
        err = InfraError(code="S3_ERROR", message="bucket unavailable")
        assert err.code == "S3_ERROR"
        assert err.message == "bucket unavailable"
        assert err.cause is None

    def test_infra_error_with_cause(self) -> None:
        original = ValueError("original error")
        err = InfraError(code="WRAPPED", message="wrapped", cause=original)
        assert err.cause is original

    def test_infra_error_repr_contains_code(self) -> None:
        err = InfraError(code="MY_CODE", message="details")
        assert "MY_CODE" in repr(err)

    def test_tenant_mismatch_error_is_infra_error(self) -> None:
        err = TenantMismatchError(resource="s3_key", detail="wrong prefix")
        assert isinstance(err, InfraError)
        assert isinstance(err, Exception)

    def test_tenant_mismatch_error_code_is_fixed(self) -> None:
        err = TenantMismatchError(resource="pinecone_vector", detail="tid mismatch")
        assert err.code == "TENANT_MISMATCH"

    def test_tenant_mismatch_error_stores_resource(self) -> None:
        err = TenantMismatchError(resource="neo4j_db", detail="cross-tenant")
        assert err.resource == "neo4j_db"
        assert "neo4j_db" in err.message

    def test_tenant_mismatch_error_default_detail(self) -> None:
        err = TenantMismatchError(resource="s3_key")
        assert err.detail == ""


# ---------------------------------------------------------------------------
# 2. S3Adapter — runtime_checkable + key-prefix guard
# ---------------------------------------------------------------------------


class TestS3AdapterProtocol:
    def test_s3adapter_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeS3(), S3Adapter)

    def test_assert_tenant_key_valid(self) -> None:
        ctx = _make_ctx()
        valid_key = f"{_TENANT_ID}/documents/doc1/v1/original.pdf"
        assert_tenant_key(ctx, valid_key)  # must not raise

    def test_assert_tenant_key_wrong_prefix_raises(self) -> None:
        ctx = _make_ctx()
        wrong_key = f"{_OTHER_TENANT_ID}/documents/doc1/v1/original.pdf"
        with pytest.raises(TenantMismatchError) as exc_info:
            assert_tenant_key(ctx, wrong_key)
        assert exc_info.value.resource == "s3_key"

    def test_assert_tenant_key_no_prefix_raises(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(TenantMismatchError):
            assert_tenant_key(ctx, "documents/doc1/file.pdf")


# ---------------------------------------------------------------------------
# 3. SqsAdapter — runtime_checkable + ReceivedMessage dataclass
# ---------------------------------------------------------------------------


class TestSqsAdapterProtocol:
    def test_sqs_adapter_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeSqs(), SqsAdapter)

    def test_received_message_is_frozen(self) -> None:
        msg = ReceivedMessage(
            message_id="mid",
            receipt_handle="rh",
            body={"key": "value"},
            attributes={"ApproximateReceiveCount": "1"},
            attempt=1,
        )
        with pytest.raises(FrozenInstanceError):
            msg.attempt = 2  # type: ignore[misc]

    def test_received_message_asdict(self) -> None:
        msg = ReceivedMessage(
            message_id="mid",
            receipt_handle="rh",
            body={"key": "value"},
            attributes={"ApproximateReceiveCount": "1"},
            attempt=1,
        )
        d = asdict(msg)
        assert d["message_id"] == "mid"
        assert d["attempt"] == 1
        assert d["body"] == {"key": "value"}


# ---------------------------------------------------------------------------
# 4. PineconeAdapter — runtime_checkable + VectorRecord / QueryMatch dataclasses
# ---------------------------------------------------------------------------


class TestPineconeAdapterProtocol:
    def test_pinecone_adapter_is_runtime_checkable(self) -> None:
        assert isinstance(_FakePinecone(), PineconeAdapter)

    def test_vector_record_is_frozen(self) -> None:
        rec = VectorRecord(
            id="doc1:v1:0",
            values=(0.1, 0.2, 0.3),
            metadata={"tenant_id": str(_TENANT_ID)},
        )
        with pytest.raises(FrozenInstanceError):
            rec.id = "changed"  # type: ignore[misc]

    def test_vector_record_asdict(self) -> None:
        rec = VectorRecord(
            id="doc1:v1:0",
            values=(0.1,) * 5,
            metadata={"tenant_id": str(_TENANT_ID), "doc_id": "uuid"},
        )
        d = asdict(rec)
        assert d["id"] == "doc1:v1:0"
        assert d["values"] == (0.1,) * 5

    def test_query_match_is_frozen(self) -> None:
        match = QueryMatch(id="vec1", score=0.95, metadata={"tenant_id": "t1"})
        with pytest.raises(FrozenInstanceError):
            match.score = 0.1  # type: ignore[misc]

    def test_query_match_asdict(self) -> None:
        match = QueryMatch(
            id="vec1",
            score=0.85,
            metadata={"tenant_id": str(_TENANT_ID)},
        )
        d = asdict(match)
        assert d["id"] == "vec1"
        assert d["score"] == 0.85

    def test_assert_vector_tenant_matching(self) -> None:
        ctx = _make_ctx()
        metadata: dict[str, Any] = {"tenant_id": str(_TENANT_ID)}
        _assert_vector_tenant(ctx, metadata)  # must not raise

    def test_assert_vector_tenant_mismatch_raises(self) -> None:
        ctx = _make_ctx()
        metadata: dict[str, Any] = {"tenant_id": str(_OTHER_TENANT_ID)}
        with pytest.raises(TenantMismatchError) as exc_info:
            _assert_vector_tenant(ctx, metadata)
        assert exc_info.value.resource == "pinecone_vector_metadata"

    def test_assert_vector_tenant_missing_key_raises(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(TenantMismatchError):
            _assert_vector_tenant(ctx, {})


# ---------------------------------------------------------------------------
# 5. Neo4jAdapter — runtime_checkable + Transaction protocol
# ---------------------------------------------------------------------------


class TestNeo4jAdapterProtocol:
    def test_neo4j_adapter_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeNeo4j(), Neo4jAdapter)

    def test_transaction_protocol_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeTx(), Transaction)


# ---------------------------------------------------------------------------
# 6. EmbeddingsAdapter — runtime_checkable
# ---------------------------------------------------------------------------


class TestEmbeddingsAdapterProtocol:
    def test_embeddings_adapter_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeEmbeddings(), EmbeddingsAdapter)

    def test_embedding_dimension_constant_matches_titan_v2(self) -> None:
        """Verify the EMBEDDING_DIMENSION constant matches Titan v2 spec (1 536)."""
        from app.infra.embeddings import EMBEDDING_DIMENSION

        assert EMBEDDING_DIMENSION == 1536


# ---------------------------------------------------------------------------
# 7. RedisAdapter — runtime_checkable + RedisPipeline protocol
# ---------------------------------------------------------------------------


class TestRedisAdapterProtocol:
    def test_redis_adapter_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeRedis(), RedisAdapter)

    def test_redis_pipeline_is_runtime_checkable(self) -> None:
        assert isinstance(_FakePipeline(), RedisPipeline)


# ---------------------------------------------------------------------------
# 8. __init__.py public surface (__all__ completeness)
# ---------------------------------------------------------------------------


class TestInfraInitPublicSurface:
    def test_all_expected_names_in_all(self) -> None:
        import app.infra as infra_pkg

        expected = {
            "InfraError",
            "TenantMismatchError",
            "EmbeddingsAdapter",
            "Neo4jAdapter",
            "Transaction",
            "PineconeAdapter",
            "QueryMatch",
            "VectorRecord",
            "RedisAdapter",
            "RedisPipeline",
            "S3Adapter",
            "ReceivedMessage",
            "SqsAdapter",
        }
        assert expected.issubset(set(infra_pkg.__all__))

    def test_all_names_are_importable(self) -> None:
        import app.infra as infra_pkg

        for name in infra_pkg.__all__:
            assert hasattr(infra_pkg, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# 9. Dataclass serialisation round-trip (asdict safety)
# ---------------------------------------------------------------------------


class TestDataclassSerialisation:
    def test_received_message_full_round_trip(self) -> None:
        msg = ReceivedMessage(
            message_id="m1",
            receipt_handle="rh1",
            body={"job_id": "j1", "tenant_id": str(_TENANT_ID)},
            attributes={"ApproximateReceiveCount": "2"},
            attempt=2,
        )
        d = asdict(msg)
        assert isinstance(d["message_id"], str)
        assert isinstance(d["body"], dict)
        assert isinstance(d["attempt"], int)
        assert d["attempt"] == 2

    def test_vector_record_values_are_tuple(self) -> None:
        rec = VectorRecord(
            id="stg:job1:0",
            values=tuple(float(i) / 100 for i in range(5)),
            metadata={"tenant_id": str(_TENANT_ID), "index_state": "staging"},
        )
        d = asdict(rec)
        # dataclasses.asdict preserves tuple elements for simple scalar types
        assert isinstance(d["values"], tuple)

    def test_query_match_metadata_preserved(self) -> None:
        metadata: dict[str, Any] = {
            "tenant_id": str(_TENANT_ID),
            "doc_id": "doc-uuid",
            "is_current": True,
        }
        match = QueryMatch(id="vec2", score=0.92, metadata=metadata)
        d = asdict(match)
        assert isinstance(d["metadata"], dict)
        assert d["metadata"]["doc_id"] == "doc-uuid"


# ---------------------------------------------------------------------------
# 10. No external SDK imports in infra protocol modules
# ---------------------------------------------------------------------------


class TestNoExternalSdkImports:
    """Verify protocol modules do not import external SDKs at module level."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "app.infra._base",
            "app.infra.s3",
            "app.infra.sqs",
            "app.infra.pinecone",
            "app.infra.neo4j",
            "app.infra.embeddings",
            "app.infra.redis",
        ],
    )
    def test_module_does_not_import_external_sdk(self, module_name: str) -> None:
        import importlib

        mod = importlib.import_module(module_name)
        forbidden = {"aioboto3", "botocore", "pinecone", "neo4j", "redis", "aioredis"}
        module_globals = vars(mod)
        for sdk in forbidden:
            assert sdk not in module_globals, (
                f"Module {module_name!r} has forbidden SDK {sdk!r} in its namespace"
            )
