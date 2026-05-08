"""Domain error model — stdlib only, no external library imports.

References:
  @docs/12-coding-conventions.md §5 (RagError dataclass pattern)
  @docs/06-api.md §1.4 (HTTP status mapping)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """All error codes used across the service.

    HTTP status mapping is defined in ``to_http_status``.
    New codes must be added to @docs/06-api.md §1.4 simultaneously.
    """

    QUESTION_EMPTY = "QUESTION_EMPTY"
    QUESTION_NO_CONTENT = "QUESTION_NO_CONTENT"
    NO_RESULTS = "NO_RESULTS"
    NO_ACCESSIBLE_RESULTS = "NO_ACCESSIBLE_RESULTS"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    SERVICE_DEGRADED = "SERVICE_DEGRADED"
    BEDROCK_UPSTREAM_ERROR = "BEDROCK_UPSTREAM_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_SYSTEM_CONTEXT = "INVALID_SYSTEM_CONTEXT"
    TENANT_CONTEXT_INVALID = "TENANT_CONTEXT_INVALID"
    BACKPRESSURE = "BACKPRESSURE"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    DUPLICATE_VERSION = "DUPLICATE_VERSION"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class RagError(Exception):
    """Domain exception raised by any layer of the service.

    ``infra/`` adapters must convert SDK-specific errors into ``RagError``
    before propagating.  ``api/`` converts ``RagError`` to HTTP responses.
    """

    code: ErrorCode
    message: str
    retryable: bool = False
    retry_after_ms: int | None = None
    fallback_used: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


_HTTP_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.QUESTION_EMPTY: 400,
    ErrorCode.QUESTION_NO_CONTENT: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.INVALID_SYSTEM_CONTEXT: 403,
    ErrorCode.NO_RESULTS: 404,
    ErrorCode.NO_ACCESSIBLE_RESULTS: 404,
    ErrorCode.DUPLICATE_FILE: 409,
    ErrorCode.DUPLICATE_VERSION: 409,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: 415,
    ErrorCode.BACKPRESSURE: 429,
    ErrorCode.TENANT_CONTEXT_INVALID: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_DEGRADED: 500,
    ErrorCode.BEDROCK_UPSTREAM_ERROR: 502,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}


def to_http_status(code: ErrorCode) -> int:
    """Return the HTTP status code for a given ``ErrorCode``.

    Falls back to 500 for any code not explicitly mapped (defensive default).
    """
    return _HTTP_STATUS_MAP.get(code, 500)
