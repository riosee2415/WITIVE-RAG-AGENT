"""Timing-safe auth helpers for internal API endpoints.

``constant_time_eq`` is a thin ``hmac.compare_digest`` wrapper that prevents
timing-based secret leakage.  ``require_internal_auth`` is the FastAPI
dependency that enforces dual-key validation on every protected endpoint.

Health-check endpoints must **not** apply ``require_internal_auth`` — they are
intentionally unauthenticated per @docs/06-api.md §6.1.

References:
  @docs/00-scope.md §3.1 (dual-key rotation)
  @docs/07-multitenancy-and-access.md §2.1 (dependency pattern)
  @docs/12-coding-conventions.md §5 (RagError / ErrorCode)
"""

from __future__ import annotations

import hmac

from fastapi import Header

from app.domain.errors import ErrorCode, RagError
from app.platform.config import get_settings

__all__ = ["constant_time_eq", "require_internal_auth"]


def constant_time_eq(a: str, b: str) -> bool:
    """Return ``True`` when *a* and *b* are equal using a constant-time comparison.

    Prevents timing side-channel attacks on secret comparison.
    Both arguments are UTF-8 encoded before comparison.

    Args:
        a: First string to compare.
        b: Second string to compare.

    Returns:
        ``True`` if the strings are identical, ``False`` otherwise.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def require_internal_auth(
    x_internal_auth: str = Header(..., alias="X-Internal-Auth"),
) -> str:
    """FastAPI dependency — validate ``X-Internal-Auth`` dual-key header.

    Accepts the header if it matches *either* the primary or secondary
    secret defined in ``Settings``.  An empty header always fails even if
    both secrets are empty (explicit empty-string auth is not valid).

    Args:
        x_internal_auth: Value of the ``X-Internal-Auth`` HTTP header.

    Returns:
        The validated header string (allows downstream code to inspect it).

    Raises:
        RagError: With ``ErrorCode.UNAUTHORIZED`` (HTTP 401) on failure.

    Docs: @docs/00-scope.md §3.1
    """
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
    return x_internal_auth
