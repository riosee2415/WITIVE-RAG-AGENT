"""API middleware — request-id injection and structlog context binding.

References:
  @docs/06-api.md §1.3 (request_id header echo)
  @docs/09-observability.md §1.2 (standard log fields)
  @docs/12-coding-conventions.md §6.3 (contextvars pattern)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from uuid_extensions import uuid7  # type: ignore[import-untyped]

from app.platform.logging import bind_request_context

_REQUEST_ID_HEADER = "X-Request-Id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Parse or generate X-Request-Id, echo it on the response, and bind it
    (plus tenant/user if already on request.state) into structlog contextvars.

    Per @docs/06-api.md §1.3: ``request_id`` is echo'd back on every response.
    If the header is absent a new uuid7 is generated (time-sortable, K-Sortable).
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the ASGI app with request-id middleware."""
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Inject request_id into state, bind structlog context, echo header."""
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid7())
        request.state.request_id = request_id

        # Bind structlog context for this async task scope.
        # tenant_id / user_id may be populated later by auth middleware.
        bind_request_context(request_id=request_id)

        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
