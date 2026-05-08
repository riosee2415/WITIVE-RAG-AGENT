"""FastAPI dependencies — TenantContext construction from X-* headers.

``require_tenant_context`` is the single dependency that every protected
endpoint uses.  It validates the internal auth secret, parses and normalises
all seven ``X-*`` headers, and returns an immutable ``TenantContext``.

References:
  @docs/00-scope.md §3.2 (X-* header contract, 7 headers)
  @docs/07-multitenancy-and-access.md §2.1 (dependency pattern)
  @docs/12-coding-conventions.md §5 (RagError / ErrorCode)
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import structlog
from fastapi import Header
from uuid_extensions import uuid7  # type: ignore[import-untyped]

from app.api._security import constant_time_eq
from app.domain.access import Level, Role
from app.domain.errors import ErrorCode, RagError
from app.domain.tenant import TenantContext, normalize_departments
from app.platform.config import get_settings
from app.platform.logging import bind_request_context

__all__ = ["require_tenant_context"]

logger = structlog.get_logger(__name__)


async def require_tenant_context(
    x_internal_auth: str = Header(..., alias="X-Internal-Auth"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-Id"),
    x_user_id: UUID = Header(..., alias="X-User-Id"),
    x_role: str = Header(..., alias="X-Role"),
    x_department: str = Header("", alias="X-Department"),
    x_level: str | None = Header(None, alias="X-Level"),
    x_hire_date: date | None = Header(None, alias="X-Hire-Date"),
    x_request_id: str | None = Header(None, alias="X-Request-Id"),
) -> TenantContext:
    """Build and return a validated ``TenantContext`` from request headers.

    Steps performed (in order):
    1. Dual-key ``X-Internal-Auth`` validation (timing-safe).
    2. ``X-Department`` header normalisation via ``normalize_departments``.
    3. ``X-Role`` -> ``Role`` enum conversion (400 on unknown value).
    4. ``X-Level`` -> ``Level`` enum conversion (400 on unknown value).
    5. ``X-Request-Id`` generation (uuid7) when absent.
    6. ``structlog`` context binding for the request scope.
    7. ``TenantContext`` construction and return.

    Args:
        x_internal_auth: Shared secret for internal service trust.
        x_tenant_id: Tenant UUID (all data access is filtered by this).
        x_user_id: Acting user UUID.
        x_role: RBAC role string (``COMPANY_USER`` etc.).
        x_department: Comma-separated department names (optional).
        x_level: Korean seniority level code (optional).
        x_hire_date: ISO-8601 hire date (optional).
        x_request_id: Distributed trace ID (generated if absent).

    Returns:
        A validated, immutable ``TenantContext``.

    Raises:
        RagError: ``UNAUTHORIZED`` (401) on auth failure.
        RagError: ``INVALID_INPUT`` (400) on unknown role or level.

    Docs:
      @docs/07-multitenancy-and-access.md §2.1
      @docs/00-scope.md §3.2
    """
    # 1. Dual-key auth validation.
    cfg = get_settings()
    primary_ok = bool(cfg.internal_auth_secret_primary) and constant_time_eq(
        x_internal_auth, cfg.internal_auth_secret_primary
    )
    secondary_ok = bool(cfg.internal_auth_secret_secondary) and constant_time_eq(
        x_internal_auth, cfg.internal_auth_secret_secondary
    )
    if not (primary_ok or secondary_ok):
        raise RagError(
            code=ErrorCode.UNAUTHORIZED,
            message="X-Internal-Auth header is missing or invalid.",
        )

    # 2. Department normalisation.
    departments = normalize_departments(x_department)

    # 3. Role parsing — unknown role -> 400 (Next.js contract violation treated
    #    as client error since the X-Role values are fixed by this service).
    try:
        role = Role(x_role)
    except ValueError as exc:
        raise RagError(
            code=ErrorCode.INVALID_REQUEST,
            message=f"Unknown X-Role value: {x_role!r}. Must be one of: {[r.value for r in Role]}",
        ) from exc

    # 4. Level parsing.
    level: Level | None = None
    if x_level is not None:
        try:
            level = Level(x_level)
        except ValueError as exc:
            raise RagError(
                code=ErrorCode.INVALID_REQUEST,
                message=f"Unknown X-Level value: {x_level!r}. "
                f"Must be one of: {[lv.value for lv in Level]}",
            ) from exc

    # 5. Request-ID generation when absent.
    request_id: str = x_request_id if x_request_id is not None else str(uuid7())

    # 6. Bind structlog context for the duration of this request.
    bind_request_context(
        request_id=request_id,
        tenant_id=str(x_tenant_id),
        user_id=str(x_user_id),
    )

    # 7. Build TenantContext.
    return TenantContext(
        tenant_id=x_tenant_id,
        user_id=x_user_id,
        role=role,
        departments=departments,
        level=level,
        hire_date=x_hire_date,
        request_id=request_id,
    )
