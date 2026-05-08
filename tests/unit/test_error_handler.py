"""Unit tests for app/api/_error_handlers.py.

Covers lines 21-22 (request_id extraction + JSONResponse construction)
by raising a real RagError through a minimal FastAPI app.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api._error_handlers import rag_error_handler
from app.domain.errors import ErrorCode, RagError


@pytest.fixture()
def error_app() -> FastAPI:
    """Minimal FastAPI app with only the RagError exception handler registered."""
    app = FastAPI()
    app.add_exception_handler(RagError, rag_error_handler)  # type: ignore[arg-type]

    @app.get("/boom")
    async def boom() -> None:
        """Raise a RagError to trigger the handler under test."""
        raise RagError(code=ErrorCode.NO_RESULTS, message="missing")

    return app


@pytest.mark.asyncio
async def test_rag_error_returned_as_json(error_app: FastAPI) -> None:
    """RagError must be serialised to the standard JSON envelope (06-api.md §1.4)."""
    transport = ASGITransport(app=error_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom")

    assert resp.status_code == 404
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "NO_RESULTS"
    assert body["error"]["message"] == "missing"
    assert body["error"]["retryable"] is False
    assert body["error"]["retry_after_ms"] is None
    assert "request_id" in body["meta"]
