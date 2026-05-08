"""structlog initialisation and logging helpers.

References:
  @docs/09-observability.md §1 (log fields, event catalogue)
  @docs/12-coding-conventions.md §6 (structlog usage)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


# ---------------------------------------------------------------------------
# Log event catalogue — free-form strings are forbidden (09 §1.2 / 12 §6.1)
# Only the minimum set required for TASK-2 is listed here.
# New events must be added to @docs/09-observability.md §1.6 simultaneously.
# ---------------------------------------------------------------------------
class LogEvent(StrEnum):
    """Enumerated log event names. Free-form strings are forbidden (09 §1.2 / 12 §6.1)."""

    APP_STARTUP = "app.startup"
    APP_HEALTH_CHECKED = "app.health.checked"
    QUERY_RECEIVED = "query.received"
    QUERY_CACHE_HIT = "query.cache.hit"
    QUERY_CACHE_MISS = "query.cache.miss"
    QUERY_STAGE1_COMPLETED = "query.stage1.completed"
    QUERY_STAGE1_FAILED = "query.stage1.failed"
    QUERY_STAGE1_FALLBACK = "query.stage1.fallback"
    QUERY_STAGE2_RETRIEVAL_COMPLETED = "query.stage2.retrieval.completed"
    QUERY_STAGE2_RETRIEVAL_DEGRADED = "query.stage2.retrieval.degraded"
    QUERY_STAGE2_RERANK_COMPLETED = "query.stage2.rerank.completed"
    QUERY_STAGE2_RERANK_DEGRADED = "query.stage2.rerank.degraded"
    QUERY_STAGE2_GENERATION_COMPLETED = "query.stage2.generation.completed"
    QUERY_STAGE2_GENERATION_DEGRADED = "query.stage2.generation.degraded"
    QUERY_STAGE2_GENERATION_CANCELLED = "query.stage2.generation.cancelled"
    QUERY_COMPLETED = "query.completed"
    QUERY_FAILED = "query.failed"
    DOCUMENT_UPLOAD_RECEIVED = "document.upload.received"
    DOCUMENT_UPLOAD_VALIDATED = "document.upload.validated"
    DOCUMENT_UPLOAD_S3_UPLOADED = "document.upload.s3_uploaded"
    DOCUMENT_UPLOAD_SQS_PUBLISHED = "document.upload.sqs_published"
    DOCUMENT_WORKER_MESSAGE_RECEIVED = "document.worker.message.received"
    DOCUMENT_WORKER_MESSAGE_LOCKED = "document.worker.message.locked"
    DOCUMENT_WORKER_MESSAGE_RELEASED = "document.worker.message.released"
    DOCUMENT_WORKER_PARSE_COMPLETED = "document.worker.parse.completed"
    DOCUMENT_WORKER_PARSE_FAILED = "document.worker.parse.failed"
    DOCUMENT_WORKER_EMBED_COMPLETED = "document.worker.embed.completed"
    DOCUMENT_WORKER_EMBED_PARTIAL_FAILED = "document.worker.embed.partial_failed"
    DOCUMENT_WORKER_INDEX_STAGE_A_COMPLETED = "document.worker.index.stage_a.completed"
    DOCUMENT_WORKER_INDEX_STAGE_A_FAILED = "document.worker.index.stage_a.failed"
    DOCUMENT_WORKER_INDEX_STAGE_B_COMPLETED = "document.worker.index.stage_b.completed"
    DOCUMENT_WORKER_INDEX_STAGE_B_PARTIAL_SUCCESS = "document.worker.index.stage_b.partial_success"
    DOCUMENT_WORKER_INDEX_STAGE_B_FAILED = "document.worker.index.stage_b.failed"
    CIRCUIT_OPEN = "circuit.open"
    CIRCUIT_HALF_OPEN = "circuit.half_open"
    CIRCUIT_CLOSED = "circuit.closed"
    BACKPRESSURE_TRIGGERED = "backpressure.triggered"
    AUDIT_CLEANUP_COMPLETED = "audit.cleanup.completed"


def _redact_pii(
    logger: WrappedLogger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """Placeholder PII filter processor.

    Phase 1: pass-through. Full PII redaction is implemented in a later task
    per @docs/09-observability.md §1.3 (question body → SHA-256 hash only, etc.)
    structlog processor protocol requires (logger, method, event_dict) signature.
    """
    _ = (logger, method)  # structlog processor protocol — params are required
    return event_dict


def configure_logging(level: str) -> None:
    """Configure structlog with JSON output for CloudWatch Logs Insights.

    Must be called once at application startup.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.EventRenamer(to="event"),
            _redact_pii,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    import logging

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


def bind_request_context(
    request_id: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Bind per-request identifiers into structlog contextvars.

    All subsequent log calls within the same async context will automatically
    carry these fields.  Call ``structlog.contextvars.clear_contextvars()`` at
    the end of the request (e.g., in middleware finally block).
    """
    ctx: dict[str, Any] = {"request_id": request_id}
    if tenant_id is not None:
        ctx["tenant_id"] = tenant_id
    if user_id is not None:
        ctx["user_id"] = user_id
    structlog.contextvars.bind_contextvars(**ctx)
