"""Unit tests for FakeRedis — get/set/delete/incr, TTL, pipeline, key convention.

References:
  @docs/04-data-stores.md §4 (Redis key naming, TTL, invalidation)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import uuid

import pytest

from app.infra._base import InfraError
from tests.fakes.fake_redis import FakeRedis

_TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_JOB = uuid.UUID("dddddddd-0000-0000-0000-000000000004")


@pytest.fixture()
def redis() -> FakeRedis:
    """Return a fresh FakeRedis instance."""
    return FakeRedis()


# ---------------------------------------------------------------------------
# get / set / delete basics
# ---------------------------------------------------------------------------


class TestGetSetDelete:
    async def test_set_and_get_roundtrip(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        await redis.set(key, b"42")
        result = await redis.get(key)
        assert result == b"42"

    async def test_get_missing_key_returns_none(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        result = await redis.get(key)
        assert result is None

    async def test_delete_removes_key(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        await redis.set(key, b"1")
        await redis.delete(key)
        result = await redis.get(key)
        assert result is None

    async def test_delete_missing_key_is_noop(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        await redis.delete(key)  # Must not raise

    async def test_set_overwrites_existing(self, redis: FakeRedis) -> None:
        key = f"meta:tenant:{_TENANT}"
        await redis.set(key, b"old")
        await redis.set(key, b"new")
        result = await redis.get(key)
        assert result == b"new"


# ---------------------------------------------------------------------------
# incr
# ---------------------------------------------------------------------------


class TestIncr:
    async def test_incr_creates_key_at_one(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        val = await redis.incr(key)
        assert val == 1

    async def test_incr_increments_existing(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        await redis.set(key, b"5")
        val = await redis.incr(key)
        assert val == 6

    async def test_incr_multiple_times(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        for expected in range(1, 6):
            val = await redis.incr(key)
            assert val == expected


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestTtlExpiry:
    async def test_set_with_ttl_returns_value_before_expiry(self, redis: FakeRedis) -> None:
        key = f"job:{_JOB}"
        await redis.set(key, b'{"status":"running"}', ttl_s=5)
        result = await redis.get(key)
        assert result == b'{"status":"running"}'

    async def test_set_with_ttl_returns_none_after_expiry(self, redis: FakeRedis) -> None:
        key = f"job:{_JOB}"
        await redis.set(key, b'{"status":"running"}', ttl_s=5)
        redis.advance_time(10)
        result = await redis.get(key)
        assert result is None

    async def test_no_ttl_does_not_expire(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        await redis.set(key, b"100")
        redis.advance_time(86400)  # 1 day
        result = await redis.get(key)
        assert result == b"100"

    async def test_advance_time_does_not_affect_other_keys(self, redis: FakeRedis) -> None:
        short_key = f"job:{_JOB}"
        long_key = f"epoch:{_TENANT}"
        await redis.set(short_key, b"short", ttl_s=1)
        await redis.set(long_key, b"permanent")
        redis.advance_time(5)
        assert await redis.get(short_key) is None
        assert await redis.get(long_key) == b"permanent"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestPipeline:
    async def test_pipeline_set_and_execute(self, redis: FakeRedis) -> None:
        pipe = await redis.pipeline()
        key = f"meta:tenant:{_TENANT}"
        pipe.set(key, b'{"host":"pc-host"}')
        results = await pipe.execute()
        assert results[0] is None
        stored = await redis.get(key)
        assert stored == b'{"host":"pc-host"}'

    async def test_pipeline_delete_and_execute(self, redis: FakeRedis) -> None:
        key = f"meta:tenant:{_TENANT}"
        await redis.set(key, b"to-delete")
        pipe = await redis.pipeline()
        pipe.delete(key)
        await pipe.execute()
        assert await redis.get(key) is None

    async def test_pipeline_incr_returns_new_value(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        pipe = await redis.pipeline()
        pipe.incr(key)
        results = await pipe.execute()
        assert results[0] == 1

    async def test_pipeline_multiple_commands_sequential(self, redis: FakeRedis) -> None:
        key1 = f"epoch:{_TENANT}"
        key2 = f"meta:tenant:{_TENANT}"
        pipe = await redis.pipeline()
        pipe.incr(key1)
        pipe.set(key2, b'{"v":1}')
        pipe.incr(key1)
        results = await pipe.execute()
        # Results: [1, None, 2]
        assert results[0] == 1
        assert results[1] is None
        assert results[2] == 2
        assert await redis.get(key2) == b'{"v":1}'

    async def test_pipeline_execute_clears_commands(self, redis: FakeRedis) -> None:
        key = f"epoch:{_TENANT}"
        pipe = await redis.pipeline()
        pipe.incr(key)
        await pipe.execute()
        # Second execute should process no commands
        results2 = await pipe.execute()
        assert results2 == []

    async def test_pipeline_set_with_ttl(self, redis: FakeRedis) -> None:
        key = f"job:{_JOB}"
        pipe = await redis.pipeline()
        pipe.set(key, b"value", ttl_s=5)
        await pipe.execute()
        assert await redis.get(key) == b"value"
        redis.advance_time(10)
        assert await redis.get(key) is None


# ---------------------------------------------------------------------------
# Key format validation
# ---------------------------------------------------------------------------


class TestKeyFormatValidation:
    async def test_valid_epoch_key_accepted(self, redis: FakeRedis) -> None:
        await redis.set(f"epoch:{_TENANT}", b"1")

    async def test_valid_meta_doc_key_accepted(self, redis: FakeRedis) -> None:
        doc_id = uuid.uuid4()
        await redis.set(f"meta:doc:{_TENANT}:{doc_id}", b'{"v":1}')

    async def test_valid_meta_tenant_key_accepted(self, redis: FakeRedis) -> None:
        await redis.set(f"meta:tenant:{_TENANT}", b'{"host":"h"}')

    async def test_valid_meta_user_key_accepted(self, redis: FakeRedis) -> None:
        await redis.set(f"meta:user:{_USER}", b'{"role":"USER"}')

    async def test_valid_job_key_accepted(self, redis: FakeRedis) -> None:
        await redis.set(f"job:{_JOB}", b'{"status":"ok"}')

    async def test_valid_dup_key_accepted(self, redis: FakeRedis) -> None:
        sha = "abc123def456" * 2  # 24-char hash-like string
        await redis.set(f"dup:{_USER}:{sha}", b"1")

    async def test_valid_rag_q1_key_accepted(self, redis: FakeRedis) -> None:
        await redis.set(f"rag:q1:{_TENANT}:epoch1:sig:sha", b"cached")

    async def test_valid_rag_q2_key_accepted(self, redis: FakeRedis) -> None:
        await redis.set(f"rag:q2:{_TENANT}:epoch2:sig:sha", b"cached")

    async def test_invalid_key_raises_infra_error(self, redis: FakeRedis) -> None:
        with pytest.raises(InfraError) as exc_info:
            await redis.get("KEYS *")  # Forbidden SCAN/KEYS pattern
        assert exc_info.value.code == "INVALID_KEY"

    async def test_arbitrary_key_raises_infra_error(self, redis: FakeRedis) -> None:
        with pytest.raises(InfraError) as exc_info:
            await redis.set("some:random:key", b"value")
        assert exc_info.value.code == "INVALID_KEY"

    async def test_pipeline_invalid_key_raises_on_queue(self, redis: FakeRedis) -> None:
        pipe = await redis.pipeline()
        with pytest.raises(InfraError) as exc_info:
            pipe.set("bad_key", b"value")
        assert exc_info.value.code == "INVALID_KEY"
