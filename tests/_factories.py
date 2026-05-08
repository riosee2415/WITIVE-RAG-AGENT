"""Test factories — shared helpers for building test domain objects.

All helpers return domain objects or value objects suitable for use in
unit and integration tests.  No external SDK calls are made.

References:
  @docs/12-coding-conventions.md §8.3 (factories in tests/_factories.py)
  @docs/07-multitenancy-and-access.md §1.1 (TenantContext)
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.domain.access import Level, Role
from app.domain.tenant import TenantContext

_DEFAULT_TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
_DEFAULT_USER_ID = UUID("20000000-0000-0000-0000-000000000002")
_DEFAULT_REQUEST_ID = "test-request-id-000"


def build_tenant_context(
    *,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    role: Role = Role.COMPANY_MANAGER,
    departments: tuple[str, ...] = (),
    level: Level | None = None,
    hire_date: date | None = None,
    request_id: str = _DEFAULT_REQUEST_ID,
) -> TenantContext:
    """Return a fresh ``TenantContext`` suitable for unit tests.

    Defaults to ``COMPANY_MANAGER`` role so that upload tests work
    without extra setup.  Override ``role`` to test other access scenarios.

    Args:
        tenant_id: Tenant UUID (defaults to a fixed test UUID).
        user_id: User UUID (defaults to a fixed test UUID).
        role: RBAC role (default ``COMPANY_MANAGER``).
        departments: Normalised department tuple.
        level: Optional seniority level.
        hire_date: Optional hire date.
        request_id: Distributed trace ID string.

    Returns:
        An immutable ``TenantContext`` instance.
    """
    return TenantContext(
        tenant_id=tenant_id or _DEFAULT_TENANT_ID,
        user_id=user_id or _DEFAULT_USER_ID,
        role=role,
        departments=departments,
        level=level,
        hire_date=hire_date,
        request_id=request_id,
    )
