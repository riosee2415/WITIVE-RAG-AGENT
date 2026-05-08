"""Unit tests for POST /internal/documents/upload.

Scenarios covered:
  - Role-based access control (USER→403, MANAGER→202, ADMIN→202, SUPER→202).
  - MIME type rejection (text/plain → 415).
  - Magic-byte mismatch (PDF MIME + DOCX magic → 415).
  - File size limit (>100 MB → 413).
  - Happy-path upload (202 Accepted + body schema).
  - SHA-256 deduplication (second upload → 409; overwrite flag → 202).
  - access_level coherence (DEPARTMENT + no departments → 400).

References:
  @docs/06-api.md §4.1 (upload response schema, error codes)
  @docs/03-document-pipeline.md §2.1 (validation rules)
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from httpx import AsyncClient

from app.domain.access import Role
from app.platform.config import get_settings

_SETTINGS = get_settings()

# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

_AUTH_HEADER = "test-secret"
_TENANT_ID = "10000000-0000-0000-0000-000000000001"
_USER_ID = "20000000-0000-0000-0000-000000000002"
_COMMON_HEADERS: dict[str, str] = {
    "X-Internal-Auth": _AUTH_HEADER,
    "X-Tenant-Id": _TENANT_ID,
    "X-User-Id": _USER_ID,
    "X-Role": Role.COMPANY_MANAGER,
}

_PDF_MAGIC = b"%PDF-1.4 fake content for testing purposes only"
_DOCX_MAGIC = b"PK\x03\x04" + b"\x00" * 40  # ZIP magic (DOCX)
_HTML_CONTENT = b"<!DOCTYPE html><html><body>test</body></html>"
_PLAIN_TEXT = b"just plain text no magic"


def _make_form(**overrides: Any) -> dict[str, Any]:
    """Return a multipart form dict with sensible defaults."""
    defaults: dict[str, Any] = {
        "doc_name": "취업규칙",
        "version": "1.0",
        "effective_date": str(date(2024, 1, 1)),
        "access_level": "COMPANY_WIDE",
    }
    defaults.update(overrides)
    return defaults


def _pdf_file(content: bytes = _PDF_MAGIC) -> tuple[str, io.BytesIO, str]:
    """Return an httpx-compatible ``(filename, fileobj, content_type)`` tuple for a PDF upload."""
    return ("document.pdf", io.BytesIO(content), "application/pdf")


def _file_tuple(content: bytes, mime: str) -> tuple[str, io.BytesIO, str]:
    """Return an httpx-compatible file tuple with *mime* as the content-type."""
    ext_map = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "text/html": "html",
        "text/plain": "txt",
    }
    ext = ext_map.get(mime, "bin")
    return (f"document.{ext}", io.BytesIO(content), mime)


async def _upload(
    client: AsyncClient,
    *,
    file_tuple: tuple[str, Any, str] | None = None,
    form: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Helper — perform a multipart upload and return the response."""
    _file = file_tuple or _pdf_file()
    _form = form or _make_form()
    _headers = headers if headers is not None else _COMMON_HEADERS

    return await client.post(
        "/internal/documents/upload",
        headers=_headers,
        files={"file": _file},
        data=_form,
    )


# ------------------------------------------------------------------
# Role-based access control
# ------------------------------------------------------------------


class TestRoleAuthorisation:
    """Verify that only MANAGER-or-above roles are allowed to upload."""

    async def test_company_user_gets_403(self, client: AsyncClient) -> None:
        """COMPANY_USER must be rejected with 403 FORBIDDEN."""
        headers = {**_COMMON_HEADERS, "X-Role": Role.COMPANY_USER}
        resp = await _upload(client, headers=headers)
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    async def test_company_manager_gets_202(self, client: AsyncClient) -> None:
        """COMPANY_MANAGER must be accepted with 202 Accepted."""
        headers = {**_COMMON_HEADERS, "X-Role": Role.COMPANY_MANAGER}
        resp = await _upload(client, headers=headers)
        assert resp.status_code == 202

    async def test_company_admin_gets_202(self, client: AsyncClient) -> None:
        """COMPANY_ADMIN must be accepted with 202 Accepted."""
        headers = {**_COMMON_HEADERS, "X-Role": Role.COMPANY_ADMIN}
        resp = await _upload(client, headers=headers)
        assert resp.status_code == 202

    async def test_super_admin_gets_202(self, client: AsyncClient) -> None:
        """WITIVE_SUPER_ADMIN must be accepted with 202 Accepted."""
        headers = {**_COMMON_HEADERS, "X-Role": Role.WITIVE_SUPER_ADMIN}
        resp = await _upload(client, headers=headers)
        assert resp.status_code == 202


# ------------------------------------------------------------------
# MIME type validation
# ------------------------------------------------------------------


class TestMimeValidation:
    """Verify MIME whitelist enforcement."""

    async def test_plain_text_rejected(self, client: AsyncClient) -> None:
        """text/plain must return 415 UNSUPPORTED_MEDIA_TYPE."""
        resp = await _upload(
            client,
            file_tuple=_file_tuple(_PLAIN_TEXT, "text/plain"),
        )
        assert resp.status_code == 415
        assert resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    async def test_pdf_mime_accepted(self, client: AsyncClient) -> None:
        """application/pdf with correct magic bytes must be accepted."""
        resp = await _upload(client, file_tuple=_pdf_file())
        assert resp.status_code == 202


# ------------------------------------------------------------------
# Magic-byte verification
# ------------------------------------------------------------------


class TestMagicByteVerification:
    """Verify that MIME and file magic bytes must agree."""

    async def test_pdf_mime_with_docx_magic_rejected(self, client: AsyncClient) -> None:
        """PDF MIME + DOCX (ZIP) magic bytes must return 415."""
        resp = await _upload(
            client,
            file_tuple=_file_tuple(_DOCX_MAGIC, "application/pdf"),
        )
        assert resp.status_code == 415
        assert resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    async def test_docx_mime_with_docx_magic_accepted(self, client: AsyncClient) -> None:
        """DOCX MIME + ZIP magic bytes must be accepted."""
        resp = await _upload(
            client,
            file_tuple=_file_tuple(
                _DOCX_MAGIC,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        assert resp.status_code == 202

    async def test_html_accepted(self, client: AsyncClient) -> None:
        """text/html with DOCTYPE magic must be accepted."""
        resp = await _upload(
            client,
            file_tuple=_file_tuple(_HTML_CONTENT, "text/html"),
        )
        assert resp.status_code == 202


# ------------------------------------------------------------------
# Size limit
# ------------------------------------------------------------------


class TestSizeLimit:
    """Verify the 100 MB upload size cap."""

    async def test_oversized_file_rejected(self, client: AsyncClient) -> None:
        """A file one byte over 100 MB must return 413 PAYLOAD_TOO_LARGE."""
        # Use a small fake body prefixed with the PDF magic, then extend.
        limit = _SETTINGS.max_upload_bytes
        body = _PDF_MAGIC + b"\x00" * (limit - len(_PDF_MAGIC) + 1)
        resp = await _upload(
            client,
            file_tuple=_file_tuple(body, "application/pdf"),
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


# ------------------------------------------------------------------
# Happy path — response schema
# ------------------------------------------------------------------


class TestHappyPath:
    """Verify the 202 response shape matches @docs/06-api.md §4.1."""

    async def test_202_response_schema(self, client: AsyncClient) -> None:
        """202 Accepted body must contain job_id, doc_id, status, estimated_seconds."""
        resp = await _upload(client)
        assert resp.status_code == 202
        body = resp.json()

        data = body["data"]
        assert "job_id" in data
        assert "doc_id" in data
        assert "version" in data
        assert data["status"] == "QUEUED"
        assert isinstance(data["estimated_seconds"], int)
        assert "request_id" in body["meta"]

    async def test_202_has_unique_job_ids(self, client: AsyncClient) -> None:
        """Each upload must produce a distinct job_id."""
        r1 = await _upload(client, file_tuple=_file_tuple(_PDF_MAGIC + b"v1", "application/pdf"))
        r2 = await _upload(client, file_tuple=_file_tuple(_PDF_MAGIC + b"v2", "application/pdf"))
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["data"]["job_id"] != r2.json()["data"]["job_id"]


# ------------------------------------------------------------------
# SHA-256 deduplication
# ------------------------------------------------------------------


class TestSha256Deduplication:
    """Verify duplicate-file detection via S3 hash sentinel."""

    async def test_second_upload_same_file_returns_409(self, client: AsyncClient) -> None:
        """Uploading the same file twice (no overwrite flag) → 409 DUPLICATE_FILE."""
        first = await _upload(client)
        assert first.status_code == 202

        second = await _upload(client)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "DUPLICATE_FILE"

    async def test_overwrite_flag_bypasses_duplicate_check(self, client: AsyncClient) -> None:
        """Uploading same file with overwrite_if_duplicate=true → 202 on second attempt."""
        first = await _upload(client)
        assert first.status_code == 202

        second = await _upload(
            client,
            form=_make_form(overwrite_if_duplicate="true"),
        )
        assert second.status_code == 202


# ------------------------------------------------------------------
# access_level coherence
# ------------------------------------------------------------------


class TestAccessLevelCoherence:
    """Verify that access_level-specific required fields are enforced."""

    async def test_department_without_allowed_departments_returns_400(
        self,
        client: AsyncClient,
    ) -> None:
        """access_level=DEPARTMENT with no allowed_departments must return 400."""
        resp = await _upload(
            client,
            form=_make_form(access_level="DEPARTMENT"),
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_REQUEST"


# ------------------------------------------------------------------
# Auth header validation
# ------------------------------------------------------------------


class TestAuthValidation:
    """Verify that missing or wrong X-Internal-Auth returns 401."""

    async def test_missing_auth_header_returns_401(self, client: AsyncClient) -> None:
        """Request without X-Internal-Auth must return 422 (FastAPI missing field)."""
        headers = {k: v for k, v in _COMMON_HEADERS.items() if k != "X-Internal-Auth"}
        resp = await _upload(client, headers=headers)
        # FastAPI returns 422 for missing required Header field.
        assert resp.status_code == 422

    async def test_wrong_auth_secret_returns_401(self, client: AsyncClient) -> None:
        """Wrong X-Internal-Auth must return 401 UNAUTHORIZED."""
        headers = {**_COMMON_HEADERS, "X-Internal-Auth": "wrong-secret"}
        resp = await _upload(client, headers=headers)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"
