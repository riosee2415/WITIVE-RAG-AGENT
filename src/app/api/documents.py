"""Documents API router -- upload and job status endpoints.

Endpoints:
  POST /internal/documents/upload -- multipart file upload, returns 202 Accepted.

References:
  @docs/06-api.md §4.1 (upload endpoint spec + response schema)
  @docs/03-document-pipeline.md §2 (synchronous handler steps)
  @docs/12-coding-conventions.md §3.2 (api -> pipeline -> infra dependency order)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.api._dependencies import require_tenant_context
from app.domain.access import AccessLevel, Level
from app.domain.errors import ErrorCode, RagError
from app.domain.tenant import TenantContext
from app.pipeline.upload import UploadDocumentInput, UploadDocumentUseCase

__all__ = ["router"]

router = APIRouter(prefix="/internal/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Dependency factories -- injected by main.py; overridable in tests
# ---------------------------------------------------------------------------


def _get_upload_use_case() -> UploadDocumentUseCase:
    """Return the ``UploadDocumentUseCase`` wired to real adapters.

    In ``dev``/``test`` environments the dependency is overridden with fakes
    by the test fixture via ``app.dependency_overrides``.

    Raises:
        RuntimeError: Always in production if real adapters are not yet
            implemented (Phase 1 placeholder).
    """
    raise RuntimeError(
        "Real adapter wiring is not yet implemented (Phase 2+). "
        "Override this dependency in tests via app.dependency_overrides."
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/upload", status_code=202)
async def upload_document(
    ctx: Annotated[TenantContext, Depends(require_tenant_context)],
    use_case: Annotated[UploadDocumentUseCase, Depends(_get_upload_use_case)],
    file: UploadFile = File(..., description="Document binary (PDF, DOCX, XLSX, HTML)."),
    doc_name: str = Form(..., min_length=1, max_length=256),
    version: str = Form(..., description="Semver-like string; Next.js assigns this."),
    effective_date: date = Form(...),
    access_level: AccessLevel = Form(...),
    allowed_departments: list[str] = Form(default_factory=list),
    allowed_levels: list[str] = Form(default_factory=list),
    allowed_user_ids: list[UUID] = Form(default_factory=list),
    overwrite_if_duplicate: bool = Form(False),
) -> JSONResponse:
    """Upload a document and queue it for asynchronous indexing.

    Accepts a ``multipart/form-data`` request with the file binary and
    structured metadata fields.  On success the response is ``202 Accepted``
    with a job receipt body.

    Args:
        ctx: Validated tenant context from request headers.
        use_case: Injected ``UploadDocumentUseCase`` instance.
        file: The document binary.
        doc_name: Human-readable document name (1-256 chars).
        version: Version string; the caller (Next.js) is responsible for
            assigning monotonically increasing versions.
        effective_date: Date from which the document takes effect.
        access_level: Who may access the document.
        allowed_departments: Required when ``access_level=DEPARTMENT``.
        allowed_levels: Required when ``access_level=LEVEL``.
        allowed_user_ids: Required when ``access_level=EXECUTIVE``.
        overwrite_if_duplicate: Skip SHA-256 dedup check when ``True``.

    Returns:
        ``202 Accepted`` with ``{"data": {...}, "meta": {...}}`` body.

    Raises:
        RagError: Propagated from ``UploadDocumentUseCase.execute``.

    Docs: @docs/06-api.md §4.1
    """
    # Read the full body (streaming deferred to Phase 2+).
    body = await file.read()

    # Parse Level strings -- the Form field delivers raw strings.
    parsed_levels: list[Level] = []
    for lv_str in allowed_levels:
        try:
            parsed_levels.append(Level(lv_str))
        except ValueError as exc:
            raise RagError(
                code=ErrorCode.INVALID_REQUEST,
                message=f"Unknown level value in allowed_levels: {lv_str!r}. "
                f"Must be one of: {[lv.value for lv in Level]}",
            ) from exc

    inp = UploadDocumentInput(
        doc_name=doc_name,
        mime_type=file.content_type or "",
        body=body,
        access_level=access_level,
        allowed_departments=tuple(allowed_departments),
        allowed_levels=tuple(parsed_levels),
        allowed_user_ids=tuple(allowed_user_ids),
        version=version,
        effective_date=effective_date,
        overwrite_on_duplicate=overwrite_if_duplicate,
    )

    output = await use_case.execute(ctx, inp)

    return JSONResponse(
        status_code=202,
        content={
            "data": {
                "job_id": str(output.job_id),
                "doc_id": str(output.doc_id),
                "version": version,
                "status": str(output.status),
                "estimated_seconds": output.estimated_seconds,
            },
            "meta": {"request_id": ctx.request_id},
        },
    )
