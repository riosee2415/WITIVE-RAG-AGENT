"""In-memory fake S3 adapter for unit tests — no external SDK required.

Implements ``S3Adapter`` (``@runtime_checkable`` Protocol) using a plain
dict store.  All tenant-isolation invariants from the real adapter are
enforced: every key must start with ``{ctx.tenant_id}/``.

References:
  @docs/04-data-stores.md §3 (S3 bucket layout)
  @docs/07-multitenancy-and-access.md §2.2 (tenant_id prefix enforcement)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final

from app.domain.tenant import TenantContext
from app.infra._base import InfraError, TenantMismatchError

__all__ = ["FakeS3"]

_PART_SIZE: Final[int] = 5 * 1024 * 1024  # 5 MB — multipart part size threshold


@dataclass(frozen=True)
class _S3Obj:
    """Internal in-memory representation of a single stored object."""

    body: bytes
    etag: str
    content_type: str
    metadata: dict[str, str]


def _make_etag(body: bytes) -> str:
    """Generate a deterministic ETag from *body*.

    Single-part: ``"<hex16>-1"``
    Follows a simplified S3 multipart ETag pattern.

    Args:
        body: The raw object body bytes.

    Returns:
        ETag string (double-quoted, e.g. ``'"abc12345678901234-1"'``).
    """
    digest = hashlib.sha256(body).hexdigest()[:16]
    part_count = max(1, math.ceil(len(body) / _PART_SIZE))
    return f'"{digest}-{part_count}"'


def _assert_tenant_prefix(ctx: TenantContext, key: str, *, param: str = "key") -> None:
    """Raise ``TenantMismatchError`` if *key* does not start with ``{tenant_id}/``.

    Args:
        ctx: The calling tenant context.
        key: The S3 key to validate.
        param: Human-readable parameter name for error messages.

    Raises:
        TenantMismatchError: If the key prefix does not match the tenant.
    """
    expected = f"{ctx.tenant_id}/"
    if not key.startswith(expected):
        raise TenantMismatchError(
            resource="s3_key",
            detail=f"{param} must start with {expected!r}, got {key!r}",
        )


class FakeS3:
    """In-memory fake implementation of ``S3Adapter``.

    Thread-safety: not guaranteed — use one instance per test coroutine.

    Attributes:
        _objects: Internal store mapping key → ``_S3Obj``.
    """

    def __init__(self) -> None:
        """Initialise an empty in-memory object store."""
        self._objects: dict[str, _S3Obj] = {}

    async def put_object(
        self,
        ctx: TenantContext,
        key: str,
        body: bytes,
        content_type: str,
        *,
        sse_kms_key_id: str | None = None,  # noqa: ARG002
    ) -> str:
        """Store *body* at *key* and return a deterministic ETag.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.
            body: Raw bytes to store.
            content_type: MIME type of the object.
            sse_kms_key_id: Ignored in the fake (no encryption).

        Returns:
            ETag of the stored object.

        Raises:
            TenantMismatchError: If *key* does not start with
                ``{ctx.tenant_id}/``.
        """
        _assert_tenant_prefix(ctx, key)
        etag = _make_etag(body)
        self._objects[key] = _S3Obj(
            body=body,
            etag=etag,
            content_type=content_type,
            metadata={},
        )
        return etag

    async def get_object(
        self,
        ctx: TenantContext,
        key: str,
        *,
        byte_range: tuple[int, int] | None = None,
    ) -> bytes:
        """Return stored bytes at *key*, optionally sliced by *byte_range*.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.
            byte_range: Optional ``(start, end)`` inclusive byte range.

        Returns:
            Raw bytes (possibly a byte-range slice).

        Raises:
            TenantMismatchError: On prefix violation.
            InfraError: If the key does not exist (``"NOT_FOUND"``).
        """
        _assert_tenant_prefix(ctx, key)
        obj = self._objects.get(key)
        if obj is None:
            raise InfraError("NOT_FOUND", f"Key not found: {key!r}")
        if byte_range is not None:
            start, end = byte_range
            return obj.body[start : end + 1]
        return obj.body

    async def head_object(
        self,
        ctx: TenantContext,
        key: str,
    ) -> dict[str, str]:
        """Return metadata headers for the object at *key*.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.

        Returns:
            Dict with ``"ETag"``, ``"Content-Length"``, ``"Content-Type"``
            and any custom metadata entries.

        Raises:
            TenantMismatchError: On prefix violation.
            InfraError: If the key does not exist.
        """
        _assert_tenant_prefix(ctx, key)
        obj = self._objects.get(key)
        if obj is None:
            raise InfraError("NOT_FOUND", f"Key not found: {key!r}")
        headers: dict[str, str] = {
            "ETag": obj.etag,
            "Content-Length": str(len(obj.body)),
            "Content-Type": obj.content_type,
        }
        headers.update(obj.metadata)
        return headers

    async def put_object_conditional(
        self,
        ctx: TenantContext,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
    ) -> str:
        """Write *body* only if the current ETag matches *if_match*.

        Args:
            ctx: Tenant context.
            key: S3 object key.
            body: New bytes to write.
            if_match: If not ``None``, the write is conditional on this
                ETag matching the current stored ETag.

        Returns:
            New ETag after a successful write.

        Raises:
            TenantMismatchError: On prefix violation.
            InfraError: With code ``"PRECONDITION_FAILED"`` if ETags differ,
                or ``"NOT_FOUND"`` if the object does not exist and
                *if_match* is provided.
        """
        _assert_tenant_prefix(ctx, key)
        if if_match is not None:
            existing = self._objects.get(key)
            if existing is None:
                raise InfraError(
                    "NOT_FOUND",
                    f"Conditional write failed: key {key!r} does not exist",
                )
            if existing.etag != if_match:
                raise InfraError(
                    "PRECONDITION_FAILED",
                    f"ETag mismatch: expected {if_match!r}, got {existing.etag!r}",
                )
        etag = _make_etag(body)
        existing_obj = self._objects.get(key)
        self._objects[key] = _S3Obj(
            body=body,
            etag=etag,
            content_type=existing_obj.content_type if existing_obj else "application/octet-stream",
            metadata=existing_obj.metadata if existing_obj else {},
        )
        return etag

    async def list_objects(
        self,
        ctx: TenantContext,
        prefix: str,
        *,
        max_keys: int = 1000,
    ) -> list[str]:
        """Return sorted keys that start with *prefix*, up to *max_keys*.

        Args:
            ctx: Tenant context; *prefix* must start with ``{tenant_id}/``.
            prefix: S3 key prefix to filter by.
            max_keys: Maximum number of keys to return.

        Returns:
            Sorted list of matching keys.

        Raises:
            TenantMismatchError: If *prefix* does not start with the tenant prefix.
        """
        _assert_tenant_prefix(ctx, prefix, param="prefix")
        matching = sorted(k for k in self._objects if k.startswith(prefix))
        return matching[:max_keys]

    async def copy_object(
        self,
        ctx: TenantContext,
        src_key: str,
        dst_key: str,
    ) -> None:
        """Copy object from *src_key* to *dst_key*.

        Both keys must start with the same tenant prefix.

        Args:
            ctx: Tenant context.
            src_key: Source S3 key.
            dst_key: Destination S3 key.

        Raises:
            TenantMismatchError: If either key lacks the tenant prefix.
            InfraError: If *src_key* does not exist.
        """
        _assert_tenant_prefix(ctx, src_key, param="src_key")
        _assert_tenant_prefix(ctx, dst_key, param="dst_key")
        src_obj = self._objects.get(src_key)
        if src_obj is None:
            raise InfraError("NOT_FOUND", f"Source key not found: {src_key!r}")
        self._objects[dst_key] = _S3Obj(
            body=src_obj.body,
            etag=src_obj.etag,
            content_type=src_obj.content_type,
            metadata=dict(src_obj.metadata),
        )

    async def multipart_upload(
        self,
        ctx: TenantContext,
        key: str,
        body_iterator: AsyncIterator[bytes],
        content_type: str,
    ) -> str:
        """Consume *body_iterator* and store the assembled object at *key*.

        Args:
            ctx: Tenant context; ``key`` must start with ``{tenant_id}/``.
            key: S3 object key.
            body_iterator: Async iterator yielding byte chunks.
            content_type: MIME type.

        Returns:
            ETag of the assembled object.

        Raises:
            TenantMismatchError: On prefix violation.
        """
        _assert_tenant_prefix(ctx, key)
        parts: list[bytes] = []
        async for chunk in body_iterator:
            parts.append(chunk)
        body = b"".join(parts)
        return await self.put_object(ctx, key, body, content_type)
