"""FastAPI application factory.

References:
  @docs/06-api.md §1.6 (gzip), §6.1 (health), §4.1 (documents upload)
  @docs/12-coding-conventions.md §3 (layer dependency)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from app.api._error_handlers import rag_error_handler
from app.api._middleware import RequestIdMiddleware
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.domain.errors import RagError
from app.platform.config import get_settings
from app.platform.logging import LogEvent, configure_logging


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application.

    Called by Uvicorn entry-point and by tests.  Tests override
    ``_get_upload_use_case`` via ``app.dependency_overrides`` to inject
    fake adapters without touching module-level state.
    """
    settings = get_settings()

    # Logging must be configured before the first log call.
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        """Emit APP_STARTUP log on startup; no teardown needed in Phase 1."""
        logger = structlog.get_logger(__name__)
        logger.info(
            LogEvent.APP_STARTUP,
            version=settings.app_version,
            env=settings.env,
            log_level=settings.log_level,
        )
        yield

    app = FastAPI(
        title="WITIVE Knowledge AI",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # --- Middleware (registered in reverse dispatch order) ---
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestIdMiddleware)

    # --- Exception handlers ---
    app.add_exception_handler(RagError, rag_error_handler)  # type: ignore[arg-type]

    # --- Routers ---
    app.include_router(health_router)
    app.include_router(documents_router)

    return app


app = create_app()
