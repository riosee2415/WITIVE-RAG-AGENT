"""Domain models and error types — no external library dependencies.

Public API for the ``app.domain`` package.  All symbols exported here
are importable as ``from app.domain import <Symbol>``.

Dependency rule: this package must NOT import from ``app.api``,
``app.pipeline``, ``app.infra``, ``app.platform``, or ``app.workers``.
Only stdlib imports are allowed inside any ``app.domain`` module.
"""

from app.domain.access import (
    LEVEL_RANK,
    AccessLevel,
    Level,
    Role,
    level_rank_of,
    min_level_rank,
)
from app.domain.audit import History, Source
from app.domain.document import Chunk, Document, Version
from app.domain.errors import ErrorCode, RagError, to_http_status
from app.domain.job import Job, JobStatus, Stages, StageStatus
from app.domain.parsed import Page, ParsedDocument, Section
from app.domain.tenant import (
    SYSTEM_CRON_USER_ID,
    TenantContext,
    is_admin,
    is_manager_or_above,
    normalize_departments,
)

__all__ = [
    "LEVEL_RANK",
    # tenant
    "SYSTEM_CRON_USER_ID",
    # access
    "AccessLevel",
    # document
    "Chunk",
    "Document",
    # errors
    "ErrorCode",
    # audit
    "History",
    # job
    "Job",
    "JobStatus",
    "Level",
    # parsed
    "Page",
    "ParsedDocument",
    "RagError",
    "Role",
    "Section",
    "Source",
    "StageStatus",
    "Stages",
    "TenantContext",
    "Version",
    "is_admin",
    "is_manager_or_above",
    "level_rank_of",
    "min_level_rank",
    "normalize_departments",
    "to_http_status",
]
