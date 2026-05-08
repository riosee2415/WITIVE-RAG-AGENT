"""Root conftest — shared fixtures for unit, integration, and API tests.

Fixtures provided:
  - ``tenant_context`` — a fresh ``TenantContext`` per test (COMPANY_MANAGER).
  - ``app``            — FastAPI app wired with fake adapters.
  - ``client``         — ``httpx.AsyncClient`` using ``ASGITransport``.

References:
  @docs/11-testing.md §3 (fake adapter fixtures)
  @docs/12-coding-conventions.md §8 (test conventions)
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Force test environment before any app module is imported so that
# pydantic-settings picks up the right defaults.
# ---------------------------------------------------------------------------
os.environ.setdefault("ENV", "test")
os.environ.setdefault("INTERNAL_AUTH_SECRET_PRIMARY", "test-secret")
os.environ.setdefault("SQS_INDEXING_QUEUE_URL", "fake://indexing")

from _factories import build_tenant_context

from app.api.documents import _get_upload_use_case
from app.domain.tenant import TenantContext
from app.pipeline.upload import UploadDocumentUseCase
from tests.fakes.fake_redis import FakeRedis
from tests.fakes.fake_s3 import FakeS3
from tests.fakes.fake_sqs import FakeSqs

# ---------------------------------------------------------------------------
# TenantContext
# ---------------------------------------------------------------------------


@pytest.fixture()
def tenant_context() -> TenantContext:
    """Return a fresh COMPANY_MANAGER ``TenantContext`` for each test."""
    return build_tenant_context()


# ---------------------------------------------------------------------------
# Fake adapters
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_s3() -> FakeS3:
    """Fresh in-memory S3 fake per test."""
    return FakeS3()


@pytest.fixture()
def fake_sqs() -> FakeSqs:
    """Fresh in-memory SQS fake per test."""
    return FakeSqs()


@pytest.fixture()
def fake_redis() -> FakeRedis:
    """Fresh in-memory Redis fake per test."""
    return FakeRedis()


@pytest.fixture()
def upload_use_case(
    fake_s3: FakeS3,
    fake_sqs: FakeSqs,
    fake_redis: FakeRedis,
) -> UploadDocumentUseCase:
    """``UploadDocumentUseCase`` wired with fake adapters."""
    return UploadDocumentUseCase(s3=fake_s3, sqs=fake_sqs, redis=fake_redis)


# ---------------------------------------------------------------------------
# FastAPI app + httpx client
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(
    fake_s3: FakeS3,
    fake_sqs: FakeSqs,
    fake_redis: FakeRedis,
) -> object:
    """FastAPI application with fake adapter dependency overrides."""
    from app.main import create_app

    _app = create_app()

    # Override the upload use-case dependency to inject fakes.
    def _fake_use_case() -> UploadDocumentUseCase:
        return UploadDocumentUseCase(s3=fake_s3, sqs=fake_sqs, redis=fake_redis)

    _app.dependency_overrides[_get_upload_use_case] = _fake_use_case
    return _app


@pytest.fixture()
async def client(app: object) -> AsyncClient:  # type: ignore[misc]
    """Async test client backed by the fake-wired FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as ac:
        yield ac  # type: ignore[misc]
