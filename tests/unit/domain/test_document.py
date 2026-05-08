"""Unit tests for app.domain.document."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.domain.access import AccessLevel, Level
from app.domain.document import Chunk, Document, Version

_DOC_ID = UUID("10000000-0000-0000-0000-000000000001")
_TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
_USER_ID = UUID("30000000-0000-0000-0000-000000000001")
_VERSION_ID = UUID("40000000-0000-0000-0000-000000000001")
_CHUNK_ID = UUID("50000000-0000-0000-0000-000000000001")
_NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _document(**overrides: object) -> Document:
    defaults: dict[str, object] = {
        "doc_id": _DOC_ID,
        "doc_name": "취업규칙",
        "tenant_id": _TENANT_ID,
        "access_level": AccessLevel.COMPANY_WIDE,
        "allowed_departments": (),
        "allowed_levels": (),
        "min_level_rank": None,
        "allowed_user_ids": (),
        "archived": False,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return Document(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Document __post_init__ validations
# ---------------------------------------------------------------------------


class TestDocumentValidation:
    def test_valid_company_wide(self) -> None:
        doc = _document()
        assert doc.access_level is AccessLevel.COMPANY_WIDE

    def test_department_requires_allowed_departments(self) -> None:
        with pytest.raises(ValueError, match="allowed_departments"):
            _document(access_level=AccessLevel.DEPARTMENT, allowed_departments=())

    def test_department_with_departments_ok(self) -> None:
        doc = _document(
            access_level=AccessLevel.DEPARTMENT,
            allowed_departments=("hr",),
        )
        assert doc.access_level is AccessLevel.DEPARTMENT

    def test_level_requires_allowed_levels(self) -> None:
        with pytest.raises(ValueError, match="allowed_levels"):
            _document(access_level=AccessLevel.LEVEL, allowed_levels=())

    def test_level_with_levels_ok(self) -> None:
        doc = _document(
            access_level=AccessLevel.LEVEL,
            allowed_levels=(Level.GWAJANG,),
            min_level_rank=4,
        )
        assert doc.access_level is AccessLevel.LEVEL

    def test_executive_requires_allowed_user_ids(self) -> None:
        with pytest.raises(ValueError, match="allowed_user_ids"):
            _document(access_level=AccessLevel.EXECUTIVE, allowed_user_ids=())

    def test_executive_with_user_ids_ok(self) -> None:
        doc = _document(
            access_level=AccessLevel.EXECUTIVE,
            allowed_user_ids=(_USER_ID,),
        )
        assert doc.access_level is AccessLevel.EXECUTIVE

    def test_empty_doc_name_raises(self) -> None:
        with pytest.raises(ValueError):
            _document(doc_name="")

    def test_doc_name_too_long_raises(self) -> None:
        with pytest.raises(ValueError):
            _document(doc_name="a" * 257)

    def test_doc_name_256_chars_ok(self) -> None:
        doc = _document(doc_name="a" * 256)
        assert len(doc.doc_name) == 256


# ---------------------------------------------------------------------------
# Document frozen
# ---------------------------------------------------------------------------


class TestDocumentFrozen:
    def test_frozen_raises(self) -> None:
        doc = _document()
        with pytest.raises((AttributeError, TypeError)):
            doc.doc_name = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Version frozen
# ---------------------------------------------------------------------------


class TestVersion:
    def test_creation(self) -> None:
        v = Version(
            version_id=_VERSION_ID,
            version="2.1",
            is_current=True,
            effective_date=date(2024, 1, 1),
            uploaded_at=_NOW,
        )
        assert v.version == "2.1"
        assert v.is_current is True

    def test_frozen(self) -> None:
        v = Version(
            version_id=_VERSION_ID,
            version="1.0",
            is_current=False,
            effective_date=date(2023, 1, 1),
            uploaded_at=_NOW,
        )
        with pytest.raises((AttributeError, TypeError)):
            v.is_current = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Chunk frozen + defaults
# ---------------------------------------------------------------------------


class TestChunk:
    def test_staging_defaults_false(self) -> None:
        chunk = Chunk(
            chunk_id=_CHUNK_ID,
            text="sample text",
            section="3장 2조",
            section_number="제3조",
            page=5,
            chunk_index=0,
            embedding_id="doc123:2.1:0",
            char_range=(0, 100),
        )
        assert chunk.staging is False

    def test_staging_can_be_true(self) -> None:
        chunk = Chunk(
            chunk_id=_CHUNK_ID,
            text="sample text",
            section=None,
            section_number=None,
            page=None,
            chunk_index=0,
            embedding_id="stg:job1:0",
            char_range=(0, 50),
            staging=True,
        )
        assert chunk.staging is True

    def test_frozen(self) -> None:
        chunk = Chunk(
            chunk_id=_CHUNK_ID,
            text="text",
            section=None,
            section_number=None,
            page=None,
            chunk_index=0,
            embedding_id="id",
            char_range=(0, 4),
        )
        with pytest.raises((AttributeError, TypeError)):
            chunk.text = "modified"  # type: ignore[misc]
