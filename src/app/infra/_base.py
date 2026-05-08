"""Infrastructure adapter base — protocols and shared exceptions.

All ``infra/`` adapters raise ``InfraError`` (or its subclasses) for
infrastructure-level failures.  The ``pipeline/`` layer converts these into
``RagError`` so that ``api/`` and ``domain/`` never see SDK-specific types.

References:
  @docs/12-coding-conventions.md §5.3 (external SDK error conversion)
  @docs/12-coding-conventions.md §3.2 (dependency direction — infra → domain)
"""

from __future__ import annotations

__all__ = ["InfraError", "TenantMismatchError"]


class InfraError(Exception):
    """Base exception for all infrastructure adapter failures.

    ``pipeline/`` use-cases catch ``InfraError`` and convert it to
    ``RagError`` before propagating to ``api/``.

    Args:
        code: A short machine-readable identifier (e.g. ``"S3_PUT_FAILED"``).
        message: Human-readable description of the failure.
        cause: Optional original exception that triggered this error.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        """Initialise with a machine-readable *code*, human-readable *message*, and optional *cause*.

        Args:
            code: Short machine-readable identifier (e.g. ``"S3_PUT_FAILED"``).
            message: Human-readable description.
            cause: Original exception that triggered this error, if any.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.cause = cause

    def __repr__(self) -> str:
        """Return a developer-friendly representation including code, message, and cause."""
        return (
            f"{type(self).__name__}(code={self.code!r}, message={self.message!r},"
            f" cause={self.cause!r})"
        )


class TenantMismatchError(InfraError):
    """Raised when a resource key does not belong to the requesting tenant.

    This is a security-class error: the adapter detected a cross-tenant
    access attempt (e.g. an S3 key that lacks the ``{tenant_id}/`` prefix,
    or Pinecone metadata whose ``tenant_id`` differs from ``ctx.tenant_id``).

    ``pipeline/`` should map this to ``RagError(ErrorCode.FORBIDDEN, ...)``.

    Args:
        resource: A short description of the resource (e.g. ``"s3_key"``).
        detail: Additional context (no raw user data — safe to log).
    """

    def __init__(self, resource: str, detail: str = "") -> None:
        super().__init__(
            code="TENANT_MISMATCH",
            message=f"Cross-tenant access blocked on {resource!r}: {detail}",
        )
        self.resource = resource
        self.detail = detail
