"""Unit tests for GET /internal/health.

Tests use httpx.AsyncClient + ASGITransport so no real network is needed.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture()
def app() -> object:
    return create_app()


@pytest.fixture()
async def client(app: object) -> AsyncClient:  # type: ignore[misc]
    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as ac:
        yield ac  # type: ignore[misc]


class TestHealthEndpoint:
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/internal/health")
        assert response.status_code == 200

    async def test_health_response_schema(self, client: AsyncClient) -> None:
        response = await client.get("/internal/health")
        body = response.json()

        assert "status" in body
        assert "version" in body
        assert "env" in body
        assert "timestamp" in body
        assert "dependencies" in body

        assert body["status"] == "healthy"
        assert body["dependencies"] == {}

    async def test_health_request_id_echo(self, client: AsyncClient) -> None:
        sent_id = "test-request-id-123"
        response = await client.get(
            "/internal/health",
            headers={"X-Request-Id": sent_id},
        )
        assert response.headers.get("X-Request-Id") == sent_id

    async def test_health_request_id_generated_when_missing(self, client: AsyncClient) -> None:
        response = await client.get("/internal/health")
        # No X-Request-Id was sent; server must generate one and echo it back.
        generated = response.headers.get("X-Request-Id")
        assert generated is not None
        assert len(generated) > 0
