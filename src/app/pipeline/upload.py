"""Upload document use-case — synchronous handler phase of the pipeline.

This module implements the *synchronous* part of
``POST /internal/documents/upload``:
  1. Role / MIME / magic-byte / size validation.
  2. SHA-256 deduplication check (via S3 meta-key).
  3. Document domain coherence validation.
  4. S3 PutObject (original file + job JSON).
  5. Redis SET (5-second cache).
  6. SQS send_message (triggers async Worker).

The *asynchronous* Worker phase (parsing → chunking → embedding → indexing)
is defined in ``pipeline/document/`` (Phase 2+).

References:
  @docs/03-document-pipeline.md §2 (synchronous handler steps)
  @docs/07-multitenancy-and-access.md §1.2 (Role access matrix)
  @docs/12-coding-conventions.md §5 (RagError / ErrorCode)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final
from uuid import UUID

import structlog
from uuid_extensions import uuid7  # type: ignore[import-untyped]

from app.domain.access import AccessLevel, Level
from app.domain.document import Document
from app.domain.errors import ErrorCode, RagError
from app.domain.job import Job, JobStatus, Stages
from app.domain.tenant import TenantContext, is_manager_or_above
from app.infra._base import InfraError
from app.infra.redis import RedisAdapter
from app.infra.s3 import S3Adapter
from app.infra.sqs import SqsAdapter
from app.platform.config import Settings, get_settings
from app.platform.logging import LogEvent

__all__ = ["UploadDocumentInput", "UploadDocumentOutput", "UploadDocumentUseCase"]

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MIME → file extension mapping (used to build the S3 key)
# ---------------------------------------------------------------------------

_MIME_TO_EXT: Final[dict[str, str]] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/html": "html",
}

# ---------------------------------------------------------------------------
# Magic-byte signatures for file-type verification
# ---------------------------------------------------------------------------

_MAGIC_PDF: Final[bytes] = b"%PDF-"
_MAGIC_ZIP: Final[bytes] = b"PK\x03\x04"  # DOCX and XLSX are ZIP archives
_MAGIC_HTML_DOCTYPE: Final[bytes] = b"<!DOCTYPE html"
_MAGIC_HTML_TAG: Final[bytes] = b"<html"


# ---------------------------------------------------------------------------
# Domain input / output dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadDocumentInput:
    """Input value object for ``UploadDocumentUseCase.execute``.

    All fields except ``overwrite_on_duplicate`` are required.

    Attributes:
        doc_name: Human-readable document name (1-256 chars).
        mime_type: MIME type string; must be in the ALLOWED_MIME_TYPES list.
        body: Raw file bytes.
        access_level: Who may access this document.
        allowed_departments: Required when ``access_level=DEPARTMENT``.
        allowed_levels: Required when ``access_level=LEVEL``.
        allowed_user_ids: Required when ``access_level=EXECUTIVE``.
        version: Semver-like version string supplied by Next.js.
        effective_date: Date from which the document is effective.
        overwrite_on_duplicate: Skip the SHA-256 duplicate check when ``True``.
    """

    doc_name: str
    mime_type: str
    body: bytes
    access_level: AccessLevel
    allowed_departments: tuple[str, ...]
    allowed_levels: tuple[Level, ...]
    allowed_user_ids: tuple[UUID, ...]
    version: str
    effective_date: date
    overwrite_on_duplicate: bool = False


@dataclass(frozen=True)
class UploadDocumentOutput:
    """Output value object returned from ``UploadDocumentUseCase.execute``.

    Attributes:
        job_id: UUID of the created pipeline job.
        doc_id: UUID of the document entity.
        status: Initial job status (always ``QUEUED``).
        estimated_seconds: Rough processing time estimate.
    """

    job_id: UUID
    doc_id: UUID
    status: JobStatus
    estimated_seconds: int


# ---------------------------------------------------------------------------
# Use-case
# ---------------------------------------------------------------------------


class UploadDocumentUseCase:
    """Orchestrate the synchronous upload handler steps.

    Dependencies are constructor-injected so that tests can provide fakes
    without monkey-patching.

    Attributes:
        _s3: S3 adapter for object storage.
        _sqs: SQS adapter for job queue publishing.
        _redis: Redis adapter for job state caching.
        _settings: Application settings.
    """

    def __init__(
        self,
        s3: S3Adapter,
        sqs: SqsAdapter,
        redis: RedisAdapter,
        settings: Settings | None = None,
    ) -> None:
        """Inject adapter dependencies and optional settings override.

        Args:
            s3: S3 adapter.
            sqs: SQS adapter.
            redis: Redis adapter.
            settings: Application settings; uses ``get_settings()`` when ``None``.
        """
        self._s3 = s3
        self._sqs = sqs
        self._redis = redis
        self._settings: Settings = settings if settings is not None else get_settings()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: TenantContext,
        inp: UploadDocumentInput,
    ) -> UploadDocumentOutput:
        """Run all synchronous upload steps and return the job receipt.

        Steps:
        1. Role authorisation check.
        2. MIME whitelist validation.
        3. Magic-byte file-type verification.
        4. Size limit check.
        5. SHA-256 hash computation.
        6. Deduplication check (S3 hash sentinel).
        7. Document domain coherence validation.
        8. ID generation (doc_id, version_id, job_id — all uuid7).
        9. S3 PutObject (original file).
        10. S3 PutObject (job JSON — single source of truth).
        11. Redis SET (5-second acceleration cache).
        12. SQS send_message (triggers async worker).
        13. Structured log + return ``UploadDocumentOutput``.

        Args:
            ctx: Calling tenant context (first arg by convention).
            inp: Validated upload input.

        Returns:
            ``UploadDocumentOutput`` with job receipt details.

        Raises:
            RagError: Any of FORBIDDEN / UNSUPPORTED_MEDIA_TYPE /
                PAYLOAD_TOO_LARGE / DUPLICATE_FILE / INVALID_REQUEST /
                UPSTREAM_FAILURE on corresponding failures.
        """
        # Step 1 — Role check: only MANAGER or above may upload documents.
        # MANAGER's document-group scope is validated by Next.js; we trust
        # X-Role per @docs/07 §1.2.
        if not is_manager_or_above(ctx.role):
            raise RagError(
                code=ErrorCode.FORBIDDEN,
                message=f"Role {ctx.role!r} is not permitted to upload documents. "
                "Required: COMPANY_MANAGER or above.",
            )

        # Step 2 — MIME whitelist.
        self._validate_mime(inp.mime_type)

        # Step 3 — Magic-byte verification.
        self._validate_magic_bytes(inp.mime_type, inp.body)

        # Step 4 — Size limit.
        if len(inp.body) > self._settings.max_upload_bytes:
            raise RagError(
                code=ErrorCode.PAYLOAD_TOO_LARGE,
                message=f"File size {len(inp.body):,} bytes exceeds the "
                f"{self._settings.max_upload_bytes:,}-byte limit.",
            )

        # Step 5 — SHA-256 hash.
        sha256 = hashlib.sha256(inp.body).hexdigest()

        # Step 6 — Deduplication check.
        if not inp.overwrite_on_duplicate:
            await self._check_duplicate(ctx, sha256)

        # Step 8 — Generate IDs (doc_id, job_id).
        doc_id = UUID(str(uuid7()))
        job_id = UUID(str(uuid7()))
        created_at = datetime.now(tz=UTC)

        # Step 7 — Domain coherence (Document.__post_init__ validates).

        try:
            Document(
                doc_id=doc_id,
                doc_name=inp.doc_name,
                tenant_id=ctx.tenant_id,
                access_level=inp.access_level,
                allowed_departments=inp.allowed_departments,
                allowed_levels=inp.allowed_levels,
                min_level_rank=None,  # computed at indexing time
                allowed_user_ids=inp.allowed_user_ids,
                archived=False,
                created_at=created_at,
            )
        except ValueError as exc:
            raise RagError(
                code=ErrorCode.INVALID_REQUEST,
                message=str(exc),
            ) from exc

        # Step 9 — S3 original file.
        ext = _MIME_TO_EXT[inp.mime_type]
        s3_path = f"{ctx.tenant_id}/documents/{doc_id}/{inp.version}/original.{ext}"
        try:
            await self._s3.put_object(
                ctx,
                s3_path,
                inp.body,
                inp.mime_type,
            )
        except InfraError as exc:
            raise RagError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"S3 upload failed: {exc.message}",
                retryable=True,
            ) from exc

        # Write hash sentinel key so the next upload of the same content
        # is detected as a duplicate.
        hash_key = f"{ctx.tenant_id}/doc_hash/{sha256}.json"
        hash_payload = json.dumps({"doc_id": str(doc_id), "sha256": sha256}).encode()
        try:
            await self._s3.put_object(ctx, hash_key, hash_payload, "application/json")
        except InfraError:
            # Non-fatal — sentinel missing at worst means future duplicate
            # check will miss.  Log but do not fail the upload.
            logger.warning(
                LogEvent.DOCUMENT_UPLOAD_S3_UPLOADED,
                warning="hash_sentinel_write_failed",
                doc_id=str(doc_id),
            )

        # Step 10 — Job S3 JSON (single source of truth).
        job = Job(
            job_id=job_id,
            doc_id=doc_id,
            tenant_id=ctx.tenant_id,
            version=inp.version,
            status=JobStatus.QUEUED,
            created_at=created_at,
            s3_path=f"s3://{self._settings.s3_documents_bucket}/{s3_path}",
            stages=Stages(),
            attempts=0,
        )
        job_key = f"{ctx.tenant_id}/jobs/{job_id}.json"
        job_json = json.dumps(job.to_dict()).encode()
        try:
            await self._s3.put_object(ctx, job_key, job_json, "application/json")
        except InfraError as exc:
            raise RagError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Job registration failed: {exc.message}",
                retryable=True,
            ) from exc

        # Step 11 — Redis job cache (5-second TTL; S3 is truth).
        redis_key = f"job:{job_id}"
        try:
            await self._redis.set(redis_key, job_json, ttl_s=self._settings.job_cache_ttl_s)
        except InfraError:
            # Non-fatal — cache miss is handled by §2.4 (S3 fallback).
            logger.warning(
                LogEvent.DOCUMENT_UPLOAD_S3_UPLOADED,
                warning="redis_cache_set_failed",
                job_id=str(job_id),
            )

        # Step 12 — SQS publish.
        sqs_body = {
            "job_id": str(job_id),
            "doc_id": str(doc_id),
            "tenant_id": str(ctx.tenant_id),
            "version": inp.version,
            "s3_path": job.s3_path,
            "attempt": 0,
        }
        try:
            await self._sqs.send_message(
                ctx,
                self._settings.sqs_indexing_queue_url,
                sqs_body,
                deduplication_id=str(job_id),
            )
        except InfraError as exc:
            raise RagError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"SQS publish failed: {exc.message}",
                retryable=True,
            ) from exc

        # Step 13 — Log + return.
        logger.info(
            LogEvent.DOCUMENT_UPLOAD_SQS_PUBLISHED,
            job_id=str(job_id),
            doc_id=str(doc_id),
            tenant_id=str(ctx.tenant_id),
            version=inp.version,
            mime_type=inp.mime_type,
            size_bytes=len(inp.body),
        )

        return UploadDocumentOutput(
            job_id=job_id,
            doc_id=doc_id,
            status=JobStatus.QUEUED,
            estimated_seconds=30,
        )

    # ------------------------------------------------------------------
    # Private validation helpers
    # ------------------------------------------------------------------

    def _validate_mime(self, mime_type: str) -> None:
        """Raise ``RagError(UNSUPPORTED_MEDIA_TYPE)`` when *mime_type* is not whitelisted.

        Args:
            mime_type: MIME type string from the upload request.

        Raises:
            RagError: With ``ErrorCode.UNSUPPORTED_MEDIA_TYPE`` (HTTP 415).
        """
        if mime_type not in self._settings.allowed_mime_types:
            raise RagError(
                code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                message=f"MIME type {mime_type!r} is not allowed. "
                f"Accepted types: {list(self._settings.allowed_mime_types)}",
            )

    @staticmethod
    def _validate_magic_bytes(mime_type: str, body: bytes) -> None:
        """Raise ``RagError(UNSUPPORTED_MEDIA_TYPE)`` when magic bytes mismatch MIME.

        Checks the first bytes of *body* against the expected file signature
        for the declared *mime_type*.  This prevents MIME-disguised file uploads.

        Args:
            mime_type: Declared MIME type.
            body: Raw file bytes (at least the first 16 bytes are inspected).

        Raises:
            RagError: With ``ErrorCode.UNSUPPORTED_MEDIA_TYPE`` (HTTP 415)
                when the file signature does not match the declared type.
        """
        head = body[:16]

        if mime_type == "application/pdf":
            if not head.startswith(_MAGIC_PDF):
                raise RagError(
                    code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    message="File magic bytes do not match declared MIME type application/pdf.",
                )
        elif mime_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ):
            if not head.startswith(_MAGIC_ZIP):
                raise RagError(
                    code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    message=f"File magic bytes do not match declared MIME type {mime_type!r}.",
                )
        elif mime_type == "text/html":
            # HTML can start with BOM, whitespace, or the DOCTYPE declaration.
            body_lower = head.lower()
            if not (
                _MAGIC_HTML_DOCTYPE.lower() in body_lower or _MAGIC_HTML_TAG.lower() in body_lower
            ):
                raise RagError(
                    code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    message="File magic bytes do not match declared MIME type text/html.",
                )

    async def _check_duplicate(self, ctx: TenantContext, sha256: str) -> None:
        """Raise ``RagError(DUPLICATE_FILE)`` if the hash sentinel exists in S3.

        The sentinel key format is ``{tenant_id}/doc_hash/{sha256}.json``.
        A missing object is not an error — it simply means the file is new.

        Args:
            ctx: Tenant context.
            sha256: Hex SHA-256 hash of the file body.

        Raises:
            RagError: With ``ErrorCode.DUPLICATE_FILE`` (HTTP 409) if the
                sentinel key already exists.
        """
        hash_key = f"{ctx.tenant_id}/doc_hash/{sha256}.json"
        try:
            await self._s3.head_object(ctx, hash_key)
            # head_object succeeded → sentinel exists → duplicate.
            raise RagError(
                code=ErrorCode.DUPLICATE_FILE,
                message=f"A file with SHA-256 {sha256!r} already exists for this tenant. "
                "Set overwrite_on_duplicate=true to proceed.",
            )
        except InfraError:
            # NOT_FOUND or any other InfraError means the file is new.
            pass
