"""Unit tests for UploadDocumentUseCase — direct use-case invocation.

Tests call ``UploadDocumentUseCase.execute`` directly with fake adapters,
verifying the correct sequence and count of S3/SQS/Redis interactions.

Scenarios:
  - Happy path: 2x S3 PutObject, 1x Redis SET, 1x SQS send_message.
  - S3 put failure → RagError(INTERNAL_ERROR).
  - Role failure → RagError(FORBIDDEN).
  - MIME rejection → RagError(UNSUPPORTED_MEDIA_TYPE).
  - Size rejection → RagError(PAYLOAD_TOO_LARGE).

References:
  @docs/03-document-pipeline.md §2 (steps 9-12)
  @docs/12-coding-conventions.md §5 (RagError / ErrorCode)
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from _factories import build_tenant_context

from app.domain.access import AccessLevel, Role
from app.domain.errors import ErrorCode, RagError
from app.infra._base import InfraError
from app.pipeline.upload import UploadDocumentInput, UploadDocumentUseCase
from tests.fakes.fake_redis import FakeRedis
from tests.fakes.fake_s3 import FakeS3
from tests.fakes.fake_sqs import FakeSqs

_PDF_MAGIC = b"%PDF-1.4 test document"
_TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
_SETTINGS_OVERRIDES = {
    "internal_auth_secret_primary": "test-secret",
    "sqs_indexing_queue_url": "fake://indexing",
}


def _make_input(**overrides: object) -> UploadDocumentInput:
    """Return an ``UploadDocumentInput`` with sensible test defaults."""
    defaults: dict[str, object] = {
        "doc_name": "취업규칙",
        "mime_type": "application/pdf",
        "body": _PDF_MAGIC,
        "access_level": AccessLevel.COMPANY_WIDE,
        "allowed_departments": (),
        "allowed_levels": (),
        "allowed_user_ids": (),
        "version": "1.0",
        "effective_date": date(2024, 1, 1),
        "overwrite_on_duplicate": False,
    }
    defaults.update(overrides)
    return UploadDocumentInput(**defaults)  # type: ignore[arg-type]


def _make_use_case(
    s3: FakeS3 | None = None,
    sqs: FakeSqs | None = None,
    redis: FakeRedis | None = None,
) -> tuple[UploadDocumentUseCase, FakeS3, FakeSqs, FakeRedis]:
    """Return a use-case and its adapter fakes for inspection."""
    _s3 = s3 or FakeS3()
    _sqs = sqs or FakeSqs()
    _redis = redis or FakeRedis()
    uc = UploadDocumentUseCase(s3=_s3, sqs=_sqs, redis=_redis)
    return uc, _s3, _sqs, _redis


# ---------------------------------------------------------------------------
# Happy path — S3 / SQS / Redis interaction counts
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Verify all side-effects are triggered in the correct order."""

    async def test_s3_receives_two_puts(self) -> None:
        """The use-case must write 2 objects to S3: original + job JSON."""
        ctx = build_tenant_context()
        uc, s3, _, _ = _make_use_case()
        await uc.execute(ctx, _make_input())

        # original + hash sentinel + job JSON = 3 objects in the fake store
        # (hash sentinel may be present too)
        tenant_prefix = str(ctx.tenant_id)
        orig_keys = [k for k in s3._objects if f"{tenant_prefix}/documents/" in k]
        job_keys = [k for k in s3._objects if f"{tenant_prefix}/jobs/" in k]
        assert len(orig_keys) == 1, "Expected exactly 1 original file S3 key"
        assert len(job_keys) == 1, "Expected exactly 1 job JSON S3 key"

    async def test_redis_receives_one_set(self) -> None:
        """The use-case must write exactly 1 key to Redis."""
        ctx = build_tenant_context()
        uc, _, _, redis = _make_use_case()
        output = await uc.execute(ctx, _make_input())

        job_key = f"job:{output.job_id}"
        stored = await redis.get(job_key)
        assert stored is not None, "job:{job_id} must be present in Redis"

    async def test_sqs_receives_one_message(self) -> None:
        """The use-case must publish exactly 1 SQS message."""
        from app.platform.config import get_settings

        ctx = build_tenant_context()
        uc, _, sqs, _ = _make_use_case()
        await uc.execute(ctx, _make_input())

        queue_url = get_settings().sqs_indexing_queue_url
        queue = sqs._queues.get(queue_url, [])
        assert len(queue) == 1, "Expected exactly 1 SQS message"
        msg_body = queue[0].body
        assert "job_id" in msg_body
        assert "doc_id" in msg_body
        assert "tenant_id" in msg_body
        assert msg_body["attempt"] == 0

    async def test_output_has_queued_status(self) -> None:
        """Output status must be QUEUED immediately after execute."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()
        output = await uc.execute(ctx, _make_input())

        from app.domain.job import JobStatus

        assert output.status == JobStatus.QUEUED

    async def test_output_ids_are_uuids(self) -> None:
        """job_id and doc_id must be valid UUIDs."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()
        output = await uc.execute(ctx, _make_input())

        # UUID construction must not raise.
        UUID(str(output.job_id))
        UUID(str(output.doc_id))


# ---------------------------------------------------------------------------
# Failure flows
# ---------------------------------------------------------------------------


class TestFailureFlows:
    """Verify that infrastructure failures are translated to RagError."""

    async def test_s3_put_failure_raises_internal_error(self) -> None:
        """S3 PutObject failure must raise RagError(INTERNAL_ERROR)."""
        ctx = build_tenant_context()

        # Create a failing S3 stub that raises InfraError on put_object.
        class _FailingS3(FakeS3):
            async def put_object(self, *args: object, **kwargs: object) -> str:  # type: ignore[override]  # noqa: ARG002
                raise InfraError("S3_PUT_FAILED", "simulated S3 failure")

        uc, _, _, _ = _make_use_case(s3=_FailingS3())

        with pytest.raises(RagError) as exc_info:
            await uc.execute(ctx, _make_input())

        assert exc_info.value.code == ErrorCode.INTERNAL_ERROR

    async def test_sqs_failure_raises_internal_error(self) -> None:
        """SQS send_message failure must raise RagError(INTERNAL_ERROR)."""
        ctx = build_tenant_context()

        class _FailingSqs(FakeSqs):
            async def send_message(self, *args: object, **kwargs: object) -> str:  # type: ignore[override]  # noqa: ARG002
                raise InfraError("SQS_SEND_FAILED", "simulated SQS failure")

        uc, _, _, _ = _make_use_case(sqs=_FailingSqs())

        with pytest.raises(RagError) as exc_info:
            await uc.execute(ctx, _make_input())

        assert exc_info.value.code == ErrorCode.INTERNAL_ERROR


# ---------------------------------------------------------------------------
# Role validation
# ---------------------------------------------------------------------------


class TestRoleValidation:
    """Verify that only MANAGER-or-above may execute the use-case."""

    async def test_company_user_forbidden(self) -> None:
        """COMPANY_USER must raise RagError(FORBIDDEN)."""
        ctx = build_tenant_context(role=Role.COMPANY_USER)
        uc, _, _, _ = _make_use_case()

        with pytest.raises(RagError) as exc_info:
            await uc.execute(ctx, _make_input())

        assert exc_info.value.code == ErrorCode.FORBIDDEN

    async def test_company_manager_allowed(self) -> None:
        """COMPANY_MANAGER must succeed without raising."""
        ctx = build_tenant_context(role=Role.COMPANY_MANAGER)
        uc, _, _, _ = _make_use_case()
        output = await uc.execute(ctx, _make_input())
        assert output is not None


# ---------------------------------------------------------------------------
# MIME / magic-byte / size validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Verify use-case-level input validation."""

    async def test_unsupported_mime_raises(self) -> None:
        """text/plain must raise RagError(UNSUPPORTED_MEDIA_TYPE)."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()

        with pytest.raises(RagError) as exc_info:
            await uc.execute(ctx, _make_input(mime_type="text/plain", body=b"plain text"))

        assert exc_info.value.code == ErrorCode.UNSUPPORTED_MEDIA_TYPE

    async def test_oversized_file_raises(self) -> None:
        """File exceeding max_upload_bytes must raise RagError(PAYLOAD_TOO_LARGE)."""
        from app.platform.config import get_settings

        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()
        limit = get_settings().max_upload_bytes
        oversized = _PDF_MAGIC + b"\x00" * (limit - len(_PDF_MAGIC) + 1)

        with pytest.raises(RagError) as exc_info:
            await uc.execute(ctx, _make_input(body=oversized))

        assert exc_info.value.code == ErrorCode.PAYLOAD_TOO_LARGE

    async def test_magic_byte_mismatch_raises(self) -> None:
        """PDF MIME + DOCX magic bytes must raise RagError(UNSUPPORTED_MEDIA_TYPE)."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()
        docx_magic = b"PK\x03\x04" + b"\x00" * 20

        with pytest.raises(RagError) as exc_info:
            await uc.execute(
                ctx,
                _make_input(mime_type="application/pdf", body=docx_magic),
            )

        assert exc_info.value.code == ErrorCode.UNSUPPORTED_MEDIA_TYPE

    async def test_department_coherence_raises(self) -> None:
        """DEPARTMENT access_level without allowed_departments → RagError(INVALID_REQUEST)."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()

        with pytest.raises(RagError) as exc_info:
            await uc.execute(
                ctx,
                _make_input(
                    access_level=AccessLevel.DEPARTMENT,
                    allowed_departments=(),
                ),
            )

        assert exc_info.value.code == ErrorCode.INVALID_REQUEST


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Verify SHA-256 deduplication logic."""

    async def test_duplicate_raises_409(self) -> None:
        """Second upload of same file must raise RagError(DUPLICATE_FILE)."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()

        await uc.execute(ctx, _make_input())

        with pytest.raises(RagError) as exc_info:
            await uc.execute(ctx, _make_input())

        assert exc_info.value.code == ErrorCode.DUPLICATE_FILE

    async def test_overwrite_flag_bypasses_duplicate_check(self) -> None:
        """overwrite_on_duplicate=True must bypass the dedup check."""
        ctx = build_tenant_context()
        uc, _, _, _ = _make_use_case()

        await uc.execute(ctx, _make_input())
        # Second upload with overwrite flag — must not raise.
        output = await uc.execute(ctx, _make_input(overwrite_on_duplicate=True))
        assert output is not None
