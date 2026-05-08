"""Tenant context domain model and helpers — stdlib only.

References:
  @docs/07-multitenancy-and-access.md §1.1 (TenantContext)
  @docs/07-multitenancy-and-access.md §2.1 (normalize_departments)
  @docs/07-multitenancy-and-access.md §1.2 (Role admin predicates)
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID

from app.domain.access import Level, Role

SYSTEM_CRON_USER_ID: Final[UUID] = UUID("00000000-0000-0000-0000-000000000001")
"""Reserved UUID for internal cron / system initiated calls.

Any ``TenantContext`` carrying this ``user_id`` is treated as a system
context.  Docs: @docs/07-multitenancy-and-access.md §2.3
"""


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable snapshot of the calling tenant + user identity.

    Built from the 7 ``X-*`` request headers by the FastAPI dependency
    ``require_tenant_context`` (``app/api/``).  All pipeline use-cases
    receive this as their first argument.

    Docs: @docs/07-multitenancy-and-access.md §1.1
    """

    tenant_id: UUID
    user_id: UUID
    role: Role
    departments: tuple[str, ...]
    level: Level | None
    hire_date: date | None
    request_id: str

    @property
    def is_system_cron(self) -> bool:
        """Return ``True`` when this context represents a system cron call."""
        return self.user_id == SYSTEM_CRON_USER_ID


def normalize_departments(raw: str) -> tuple[str, ...]:
    """Parse and normalise a comma-separated department string.

    Steps applied (in order):
    1. Split on commas.
    2. Strip leading/trailing whitespace from each item.
    3. NFC unicode normalisation.
    4. ASCII characters are lowercased (Korean is left as-is).
    5. Remove empty strings.
    6. Sort lexicographically for deterministic comparison.

    Duplicate entries after normalisation are preserved so that the
    caller can observe raw data anomalies; deduplication is a
    deliberate non-goal at this layer.

    Args:
        raw: Raw ``X-Department`` header value.

    Returns:
        Normalised, sorted tuple of department names.
    """
    result: list[str] = []
    for part in raw.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        normalised = unicodedata.normalize("NFC", stripped)
        # Lower-case only ASCII portion; Korean chars are unchanged.
        lowered = normalised.lower()
        result.append(lowered)
    return tuple(sorted(result))


def is_admin(role: Role) -> bool:
    """Return ``True`` when *role* has admin-level privileges.

    Admin roles: ``WITIVE_SUPER_ADMIN``, ``COMPANY_ADMIN``.
    """
    return role in (Role.WITIVE_SUPER_ADMIN, Role.COMPANY_ADMIN)


def is_manager_or_above(role: Role) -> bool:
    """Return ``True`` when *role* is manager level or above.

    Manager-or-above roles: ``WITIVE_SUPER_ADMIN``, ``COMPANY_ADMIN``,
    ``COMPANY_MANAGER``.
    """
    return role in (Role.WITIVE_SUPER_ADMIN, Role.COMPANY_ADMIN, Role.COMPANY_MANAGER)
