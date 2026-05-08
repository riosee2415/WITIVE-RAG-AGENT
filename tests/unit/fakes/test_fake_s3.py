"""Unit tests for FakeS3 — put/get roundtrip, conditional write, cross-tenant.

References:
  @docs/04-data-stores.md §3 (S3 layout)
  @docs/07-multitenancy-and-access.md §2.2 (tenant prefix enforcement)
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.access import Role
from app.domain.tenant import TenantContext
from app.infra._base import InfraError, TenantMismatchError
from tests.fakes.fake_s3 import FakeS3

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_USER = uuid.UUID("cccccccc-0000-0000-0000-000000000003")


def _ctx(tenant_id: uuid.UUID = _TENANT_A) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=_USER,
        role=Role.COMPANY_USER,
        departments=(),
        level=None,
        hire_date=None,
        request_id="req-test",
    )


@pytest.fixture()
def s3() -> FakeS3:
    """Return a fresh FakeS3 instance."""
    return FakeS3()


# ---------------------------------------------------------------------------
# put_object / get_object roundtrip
# ---------------------------------------------------------------------------


class TestPutGetRoundtrip:
    async def test_put_returns_etag(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        etag = await s3.put_object(_ctx(), key, b"hello world", "application/pdf")
        assert etag.startswith('"')
        assert etag.endswith('"')

    async def test_get_returns_stored_body(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        body = b"hello world"
        await s3.put_object(_ctx(), key, body, "application/pdf")
        result = await s3.get_object(_ctx(), key)
        assert result == body

    async def test_get_byte_range(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/v1/chunks.jsonl"
        body = b"0123456789"
        await s3.put_object(_ctx(), key, body, "application/x-ndjson")
        result = await s3.get_object(_ctx(), key, byte_range=(2, 5))
        assert result == b"2345"

    async def test_get_missing_key_raises_infra_error(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/missing.pdf"
        with pytest.raises(InfraError) as exc_info:
            await s3.get_object(_ctx(), key)
        assert exc_info.value.code == "NOT_FOUND"

    async def test_put_overwrites_existing(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        await s3.put_object(_ctx(), key, b"old content", "application/pdf")
        await s3.put_object(_ctx(), key, b"new content", "application/pdf")
        result = await s3.get_object(_ctx(), key)
        assert result == b"new content"

    async def test_etag_deterministic_for_same_body(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        body = b"deterministic body"
        etag1 = await s3.put_object(_ctx(), key, body, "application/pdf")
        key2 = f"{_TENANT_A}/documents/doc1/v2/original.pdf"
        etag2 = await s3.put_object(_ctx(), key2, body, "application/pdf")
        assert etag1 == etag2

    async def test_etag_differs_for_different_body(self, s3: FakeS3) -> None:
        key1 = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        key2 = f"{_TENANT_A}/documents/doc1/v2/original.pdf"
        etag1 = await s3.put_object(_ctx(), key1, b"body one", "application/pdf")
        etag2 = await s3.put_object(_ctx(), key2, b"body two", "application/pdf")
        assert etag1 != etag2


# ---------------------------------------------------------------------------
# head_object
# ---------------------------------------------------------------------------


class TestHeadObject:
    async def test_head_returns_etag_and_length(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        body = b"head test body"
        etag = await s3.put_object(_ctx(), key, body, "application/pdf")
        headers = await s3.head_object(_ctx(), key)
        assert headers["ETag"] == etag
        assert headers["Content-Length"] == str(len(body))
        assert headers["Content-Type"] == "application/pdf"

    async def test_head_missing_key_raises(self, s3: FakeS3) -> None:
        with pytest.raises(InfraError) as exc_info:
            await s3.head_object(_ctx(), f"{_TENANT_A}/no-such-key")
        assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# put_object_conditional
# ---------------------------------------------------------------------------


class TestConditionalWrite:
    async def test_conditional_write_matching_etag_succeeds(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/metadata.json"
        old_body = b'{"schema_version": 1}'
        etag = await s3.put_object(_ctx(), key, old_body, "application/json")
        new_body = b'{"schema_version": 2}'
        new_etag = await s3.put_object_conditional(_ctx(), key, new_body, if_match=etag)
        assert new_etag != etag
        stored = await s3.get_object(_ctx(), key)
        assert stored == new_body

    async def test_conditional_write_mismatched_etag_raises_precondition_failed(
        self, s3: FakeS3
    ) -> None:
        key = f"{_TENANT_A}/documents/doc1/metadata.json"
        await s3.put_object(_ctx(), key, b"original", "application/json")
        with pytest.raises(InfraError) as exc_info:
            await s3.put_object_conditional(_ctx(), key, b"update", if_match='"wrong-etag-1"')
        assert exc_info.value.code == "PRECONDITION_FAILED"

    async def test_conditional_write_missing_key_raises_not_found(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/metadata.json"
        with pytest.raises(InfraError) as exc_info:
            await s3.put_object_conditional(_ctx(), key, b"body", if_match='"any-etag"')
        assert exc_info.value.code == "NOT_FOUND"

    async def test_unconditional_write_succeeds_without_etag(self, s3: FakeS3) -> None:
        key = f"{_TENANT_A}/documents/doc1/metadata.json"
        etag = await s3.put_object_conditional(_ctx(), key, b"unconditional")
        assert etag.startswith('"')


# ---------------------------------------------------------------------------
# list_objects
# ---------------------------------------------------------------------------


class TestListObjects:
    async def test_list_returns_matching_keys_sorted(self, s3: FakeS3) -> None:
        ctx = _ctx()
        keys = [
            f"{_TENANT_A}/documents/doc2/v1/original.pdf",
            f"{_TENANT_A}/documents/doc1/v1/original.pdf",
            f"{_TENANT_A}/documents/doc1/v2/original.pdf",
        ]
        for key in keys:
            await s3.put_object(ctx, key, b"body", "application/pdf")
        prefix = f"{_TENANT_A}/documents/doc1/"
        result = await s3.list_objects(ctx, prefix)
        assert result == sorted(k for k in keys if k.startswith(prefix))

    async def test_list_respects_max_keys(self, s3: FakeS3) -> None:
        ctx = _ctx()
        for i in range(10):
            await s3.put_object(
                ctx,
                f"{_TENANT_A}/documents/doc1/v{i}/file.pdf",
                b"body",
                "application/pdf",
            )
        result = await s3.list_objects(ctx, f"{_TENANT_A}/documents/doc1/", max_keys=3)
        assert len(result) == 3

    async def test_list_empty_prefix_returns_empty(self, s3: FakeS3) -> None:
        ctx = _ctx()
        result = await s3.list_objects(ctx, f"{_TENANT_A}/no-such-prefix/")
        assert result == []


# ---------------------------------------------------------------------------
# copy_object
# ---------------------------------------------------------------------------


class TestCopyObject:
    async def test_copy_duplicates_object(self, s3: FakeS3) -> None:
        ctx = _ctx()
        src = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        dst = f"{_TENANT_A}/failed-parse/doc1/original.pdf"
        await s3.put_object(ctx, src, b"original content", "application/pdf")
        await s3.copy_object(ctx, src, dst)
        result = await s3.get_object(ctx, dst)
        assert result == b"original content"

    async def test_copy_src_not_found_raises(self, s3: FakeS3) -> None:
        ctx = _ctx()
        with pytest.raises(InfraError) as exc_info:
            await s3.copy_object(
                ctx,
                f"{_TENANT_A}/missing-src",
                f"{_TENANT_A}/dst",
            )
        assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# multipart_upload
# ---------------------------------------------------------------------------


class TestMultipartUpload:
    async def test_multipart_assembles_body(self, s3: FakeS3) -> None:
        ctx = _ctx()
        key = f"{_TENANT_A}/documents/doc1/v1/original.pdf"
        chunks = [b"chunk1-", b"chunk2-", b"chunk3"]

        async def body_iterator() -> object:
            for chunk in chunks:
                yield chunk

        etag = await s3.multipart_upload(ctx, key, body_iterator(), "application/pdf")  # type: ignore[arg-type]
        assert etag.startswith('"')
        result = await s3.get_object(ctx, key)
        assert result == b"chunk1-chunk2-chunk3"


# ---------------------------------------------------------------------------
# Cross-tenant enforcement (primary security requirement)
# ---------------------------------------------------------------------------


class TestCrossTenantEnforcement:
    async def test_put_wrong_tenant_prefix_raises_tenant_mismatch(self, s3: FakeS3) -> None:
        ctx_a = _ctx(_TENANT_A)
        # Key belongs to tenant B but ctx is tenant A
        key = f"{_TENANT_B}/documents/doc1/v1/original.pdf"
        with pytest.raises(TenantMismatchError) as exc_info:
            await s3.put_object(ctx_a, key, b"malicious", "application/pdf")
        assert exc_info.value.resource == "s3_key"

    async def test_get_wrong_tenant_prefix_raises_tenant_mismatch(self, s3: FakeS3) -> None:
        ctx_a = _ctx(_TENANT_A)
        key = f"{_TENANT_B}/documents/doc1/v1/original.pdf"
        with pytest.raises(TenantMismatchError):
            await s3.get_object(ctx_a, key)

    async def test_list_wrong_tenant_prefix_raises_tenant_mismatch(self, s3: FakeS3) -> None:
        ctx_a = _ctx(_TENANT_A)
        with pytest.raises(TenantMismatchError):
            await s3.list_objects(ctx_a, f"{_TENANT_B}/documents/")

    async def test_copy_src_wrong_tenant_raises_tenant_mismatch(self, s3: FakeS3) -> None:
        ctx_a = _ctx(_TENANT_A)
        with pytest.raises(TenantMismatchError):
            await s3.copy_object(
                ctx_a,
                f"{_TENANT_B}/src",
                f"{_TENANT_A}/dst",
            )

    async def test_copy_dst_wrong_tenant_raises_tenant_mismatch(self, s3: FakeS3) -> None:
        ctx_a = _ctx(_TENANT_A)
        with pytest.raises(TenantMismatchError):
            await s3.copy_object(
                ctx_a,
                f"{_TENANT_A}/src",
                f"{_TENANT_B}/dst",
            )

    async def test_key_without_any_prefix_raises_tenant_mismatch(self, s3: FakeS3) -> None:
        ctx_a = _ctx(_TENANT_A)
        with pytest.raises(TenantMismatchError):
            await s3.put_object(ctx_a, "documents/no-tenant-prefix.pdf", b"body", "application/pdf")
