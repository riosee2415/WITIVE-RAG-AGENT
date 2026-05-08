"""Health check endpoint — GET /internal/health.

Authentication is exempt per @docs/06-api.md §6.1 and §2.
ECS Task health check + ALB target group probe.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.platform.config import Settings, get_settings

router = APIRouter(prefix="/internal", tags=["health"])


class HealthResponse(BaseModel):
    """Response schema for GET /internal/health.

    ``dependencies`` is an empty dict in Phase 1 (no external I/O).
    Full dependency ping logic will be added in a later task.
    """

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    env: str
    timestamp: str  # ISO 8601 UTC
    dependencies: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Return service health status.

    Phase 1: all dependencies reported as empty dict — no external I/O.
    The status is always ``healthy`` when the process is running.
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        env=settings.env,
        timestamp=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        dependencies={},
    )
