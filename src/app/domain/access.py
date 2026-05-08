"""Access control domain models — Role, AccessLevel, Level, LEVEL_RANK.

References:
  @docs/07-multitenancy-and-access.md §1.2 (Role)
  @docs/07-multitenancy-and-access.md §1.3 (AccessLevel)
  @docs/07-multitenancy-and-access.md §1.4 (Level / LEVEL_RANK)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from types import MappingProxyType


class Role(StrEnum):
    """RBAC roles recognised by this service.

    Propagated from Next.js via ``X-Role`` header.
    Docs: @docs/07-multitenancy-and-access.md §1.2
    """

    WITIVE_SUPER_ADMIN = "WITIVE_SUPER_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    COMPANY_MANAGER = "COMPANY_MANAGER"
    COMPANY_USER = "COMPANY_USER"


class AccessLevel(StrEnum):
    """Document access level.

    Determines which 1st-store filter branch is applied.
    Docs: @docs/07-multitenancy-and-access.md §1.3
    """

    COMPANY_WIDE = "COMPANY_WIDE"
    DEPARTMENT = "DEPARTMENT"
    LEVEL = "LEVEL"
    EXECUTIVE = "EXECUTIVE"


class Level(StrEnum):
    """Korean corporate hierarchy levels (직급).

    Values are Korean strings as defined in
    @docs/07-multitenancy-and-access.md §1.4.
    """

    SAWON = "사원"
    JUIM = "주임"
    DAERI = "대리"
    GWAJANG = "과장"
    CHAJANG = "차장"
    BUJANG = "부장"
    ISA = "이사"
    SANGMU = "상무"
    JUNMU = "전무"
    SAJANG = "사장"


LEVEL_RANK: Mapping[Level, int] = MappingProxyType(
    {
        Level.SAWON: 1,
        Level.JUIM: 2,
        Level.DAERI: 3,
        Level.GWAJANG: 4,
        Level.CHAJANG: 5,
        Level.BUJANG: 6,
        Level.ISA: 7,
        Level.SANGMU: 8,
        Level.JUNMU: 9,
        Level.SAJANG: 10,
    }
)
"""Immutable rank mapping — lower number means lower seniority.

산출: @docs/07-multitenancy-and-access.md §1.4
Fail-closed: unknown levels must not match any LEVEL access filter.
"""


def level_rank_of(level: Level | str | None) -> int | None:
    """Return the rank integer for *level*, or ``None`` if unknown.

    Fail-closed policy: undefined levels return ``None`` so that any
    LEVEL-based access check fails rather than granting access.

    Args:
        level: A ``Level`` enum member, a raw string, or ``None``.

    Returns:
        Rank integer (1-10) if the level is recognised, else ``None``.
    """
    if level is None:
        return None
    try:
        return LEVEL_RANK[Level(level)]
    except (ValueError, KeyError):
        return None


def min_level_rank(allowed: Sequence[Level | str]) -> int | None:
    """Return the minimum (lowest) rank among *allowed* levels.

    Used to compute the ``min_level_rank`` stored on Document/Pinecone
    metadata at indexing time so that LEVEL access can be a simple
    ``$lte`` comparison at query time.

    Args:
        allowed: Sequence of ``Level`` enum members or raw strings.

    Returns:
        Minimum rank integer if at least one level is recognised,
        ``None`` if the sequence is empty or all levels are unknown.
    """
    ranks = [r for lv in allowed if (r := level_rank_of(lv)) is not None]
    return min(ranks) if ranks else None
