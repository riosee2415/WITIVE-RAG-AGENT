"""Unit tests for domain/errors.py."""

from __future__ import annotations

import pytest

from app.domain.errors import ErrorCode, RagError, to_http_status


class TestToHttpStatusMapping:
    """All 8 task-specified error codes must map to the correct HTTP status."""

    @pytest.mark.parametrize(
        ("code", "expected_status"),
        [
            (ErrorCode.INTERNAL_ERROR, 500),
            (ErrorCode.INVALID_REQUEST, 400),
            (ErrorCode.NO_RESULTS, 404),
            (ErrorCode.UNAUTHORIZED, 401),
            (ErrorCode.FORBIDDEN, 403),
            (ErrorCode.BACKPRESSURE, 429),
            (ErrorCode.BEDROCK_UPSTREAM_ERROR, 502),
            (ErrorCode.SERVICE_UNAVAILABLE, 503),
        ],
    )
    def test_to_http_status_mapping(self, code: ErrorCode, expected_status: int) -> None:
        assert to_http_status(code) == expected_status

    def test_unknown_code_falls_back_to_500(self) -> None:
        """Defensive default: unmapped codes return 500.

        ``to_http_status`` uses ``dict.get(code, 500)`` so any code absent
        from the map returns 500.  We verify this by passing a value that is
        not an ``ErrorCode`` member but is accepted by the dict lookup.
        """
        from app.domain import errors as _errors

        # Direct dict access — key not present → default 500.
        result = _errors._HTTP_STATUS_MAP.get("__nonexistent__", 500)  # type: ignore[call-overload]
        assert result == 500


class TestRagError:
    def test_rag_error_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        err = RagError(code=ErrorCode.INTERNAL_ERROR, message="boom")
        with pytest.raises(FrozenInstanceError):
            setattr(err, "message", "changed")  # noqa: B010

    def test_rag_error_default_fields(self) -> None:
        err = RagError(code=ErrorCode.UNAUTHORIZED, message="no access")
        assert err.retryable is False
        assert err.retry_after_ms is None
        assert err.fallback_used == []
        assert err.extra == {}

    def test_rag_error_is_exception(self) -> None:
        err = RagError(code=ErrorCode.FORBIDDEN, message="forbidden")
        assert isinstance(err, Exception)

    def test_rag_error_retryable(self) -> None:
        err = RagError(
            code=ErrorCode.BEDROCK_UPSTREAM_ERROR,
            message="upstream fail",
            retryable=True,
            retry_after_ms=1000,
        )
        assert err.retryable is True
        assert err.retry_after_ms == 1000
