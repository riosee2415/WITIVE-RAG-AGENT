"""Global exception handlers for the FastAPI application.

References:
  @docs/06-api.md §1.4 (error serialisation format)
  @docs/12-coding-conventions.md §5.2 (RagError → HTTP mapping)
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.domain.errors import RagError, to_http_status


async def rag_error_handler(request: Request, exc: RagError) -> JSONResponse:
    """Convert a ``RagError`` domain exception into a JSON HTTP response.

    Response shape follows @docs/06-api.md §1.4:
    ``{"data": null, "error": {...}, "meta": {"request_id": "..."}}``
    """
    request_id: str = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=to_http_status(exc.code),
        content={
            "data": None,
            "error": {
                "code": str(exc.code),
                "message": exc.message,
                "retryable": exc.retryable,
                "retry_after_ms": exc.retry_after_ms,
            },
            "meta": {"request_id": request_id},
        },
    )
