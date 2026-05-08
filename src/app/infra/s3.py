"""S3 adapter protocol — object storage operations with tenant isolation.

All key parameters must start with ``{tenant_id}/``; any method that
receives a key violating this invariant raises ``TenantMismatchError``
immediately — before any SDK call is made.

References:
  @docs/04-data-stores.md §3 (S3 bucket layout, SSE, retry/timeout)
  @docs/07-multitenancy-and-access.md §2.2 (tenant_id prefix enforcement)
  @docs/08-resilience.md §5.2 (timeout table for S3 operations)
  @docs/12-coding-conventions.md §3.2 (dependency direction)
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from app.domain.tenant import TenantContext
from app.infra._base import TenantMismatchError

__all__ = ["S3Adapter"]


def _assert_tenant_prefix(ctx: TenantContext, key: str) -> None:
    """Raise ``TenantMismatchError`` if *key* does not start with ``{tenant_id}/``.

    Args:
        ctx: The calling tenant context.
        key: The S3 object key to validate.

    Raises:
        TenantMismatchError: If the key prefix does not match the tenant.
    """
    expected_prefix = f"{ctx.tenant_id}/"
    if not key.startswith(expected_prefix):
        raise TenantMismatchError(
            resource="s3_key",
            detail=f"key must start with {expected_prefix!r}",
        )


@runtime_checkable
class S3Adapter(Protocol):
    """Async protocol for S3 object storage operations.

    All methods enforce tenant isolation by requiring that the *key*
    argument starts with ``{ctx.tenant_id}/``.  Implementations must
    apply SSE-KMS using ``alias/witive-tenant-{tenant_id}`` and map
    all SDK errors to ``InfraError`` subclasses.

    Timeout and retry policy follows @docs/08-resilience.md §5.2 and
    @docs/04-data-stores.md §3.6.  Implementations are responsible for
    enforcing those timeouts internally.

    See: @docs/04-data-stores.md §3
    """

    async def put_object(
        self,
        ctx: TenantContext,
        key: str,
        body: bytes,
        content_type: str,
        *,
        sse_kms_key_id: str | None = None,
    ) -> str:
        """Upload *body* to S3 at *key* and return the ETag.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key (full path within the bucket).
            body: Raw bytes to upload.
            content_type: MIME type, e.g. ``"application/pdf"``.
            sse_kms_key_id: Explicit KMS key ID/ARN.  If ``None`` the
                implementation should fall back to
                ``alias/witive-tenant-{tenant_id}``.

        Returns:
            ETag string returned by S3 (double-quoted, e.g. ``'"abc123"'``).

        Raises:
            TenantMismatchError: If *key* does not start with
                ``{ctx.tenant_id}/``.
            InfraError: For any S3/network failure.
        """
        ...

    async def get_object(
        self,
        ctx: TenantContext,
        key: str,
        *,
        byte_range: tuple[int, int] | None = None,
    ) -> bytes:
        """Download and return the body of the S3 object at *key*.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.
            byte_range: Optional ``(start, end)`` byte range (inclusive).
                Corresponds to the HTTP ``Range: bytes=start-end`` header.
                If ``None`` the full object is returned.

        Returns:
            Raw bytes of the (possibly ranged) object body.

        Raises:
            TenantMismatchError: If *key* does not start with
                ``{ctx.tenant_id}/``.
            InfraError: For any S3/network failure (including 404).
        """
        ...

    async def head_object(
        self,
        ctx: TenantContext,
        key: str,
    ) -> dict[str, str]:
        """Return the metadata headers for the S3 object at *key*.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.

        Returns:
            Mapping of HTTP response header names to values, e.g.
            ``{"ETag": '"abc123"', "Content-Length": "1234"}``.

        Raises:
            TenantMismatchError: If *key* does not start with
                ``{ctx.tenant_id}/``.
            InfraError: For any S3/network failure (including 404).
        """
        ...

    async def put_object_conditional(
        self,
        ctx: TenantContext,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
    ) -> str:
        """Write *body* to *key* only when the current ETag matches *if_match*.

        Used for ``metadata.json`` and ``jobs/*.json`` lost-update protection
        (ETag conditional write, @docs/04-data-stores.md §3.3).

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.
            body: Raw bytes to write.
            if_match: If provided, the write is conditional on the object's
                current ETag matching this value.  Pass ``None`` to write
                unconditionally (equivalent to ``put_object``).

        Returns:
            New ETag after a successful write.

        Raises:
            TenantMismatchError: If *key* does not start with
                ``{ctx.tenant_id}/``.
            InfraError: For ETag conflicts (condition failed) or any
                S3/network failure.  Callers must distinguish ETag-conflict
                errors from other failures to implement re-read-then-retry.
        """
        ...

    async def list_objects(
        self,
        ctx: TenantContext,
        prefix: str,
        *,
        max_keys: int = 1000,
    ) -> Sequence[str]:
        """Return a list of object keys under *prefix*.

        Args:
            ctx: Tenant context; ``prefix`` must start with ``{tenant_id}/``.
            prefix: S3 key prefix to list under.
            max_keys: Maximum number of keys to return (capped at 1 000 to
                avoid oversized responses).

        Returns:
            Sequence of full S3 object keys (not stripped of bucket name).

        Raises:
            TenantMismatchError: If *prefix* does not start with
                ``{ctx.tenant_id}/``.
            InfraError: For any S3/network failure.
        """
        ...

    async def copy_object(
        self,
        ctx: TenantContext,
        src_key: str,
        dst_key: str,
    ) -> None:
        """Copy the S3 object from *src_key* to *dst_key* within the same bucket.

        Used for failure-isolation prefix moves (e.g.
        ``documents/`` → ``failed-parse/``).

        Args:
            ctx: Tenant context; both *src_key* and *dst_key* must start
                with ``{tenant_id}/``.
            src_key: Source S3 object key.
            dst_key: Destination S3 object key.

        Raises:
            TenantMismatchError: If either key lacks the ``{ctx.tenant_id}/``
                prefix.
            InfraError: For any S3/network failure.
        """
        ...

    async def multipart_upload(
        self,
        ctx: TenantContext,
        key: str,
        body_iterator: AsyncIterator[bytes],
        content_type: str,
    ) -> str:
        """Stream *body_iterator* to S3 using multipart upload.

        Suitable for large objects (up to 100 MB; @docs/04-data-stores.md
        §3.6).  The implementation is responsible for part management
        (``create_multipart_upload`` / ``upload_part`` / ``complete``).

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key for the resulting object.
            body_iterator: Async iterator that yields byte chunks.
            content_type: MIME type of the final object.

        Returns:
            ETag of the completed multipart object.

        Raises:
            TenantMismatchError: If *key* does not start with
                ``{ctx.tenant_id}/``.
            InfraError: For any S3/network failure; implementations must
                abort the multipart upload on error to avoid orphaned parts.
        """
        ...


def assert_tenant_key(ctx: TenantContext, key: str) -> None:
    """Public helper to validate an S3 key against a tenant context.

    Implementations of ``S3Adapter`` should call this at the start of every
    method that accepts a *key* parameter.  Exposed here so that callers in
    ``tests/`` can also use it directly without reimplementing the check.

    Args:
        ctx: Tenant context whose ``tenant_id`` defines the expected prefix.
        key: The S3 key to validate.

    Raises:
        TenantMismatchError: If the key does not start with
            ``{ctx.tenant_id}/``.
    """
    _assert_tenant_prefix(ctx, key)
