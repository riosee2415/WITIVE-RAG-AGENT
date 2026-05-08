"""Unit tests for app.domain.audit."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.domain.audit import History, Source
from app.domain.document import Version

_DOC_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_CHUNK_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_VERSION_ID_1 = UUID("cccccccc-0000-0000-0000-000000000001")
_VERSION_ID_2 = UUID("cccccccc-0000-0000-0000-000000000002")
_NOW = datetime(2024, 1, 1, tzinfo=UTC)


class TestSource:
    def test_basic_creation(self) -> None:
        src = Source(
            chunk_id=_CHUNK_ID,
            doc_id=_DOC_ID,
            doc_name="취업규칙",
            version="2.1",
            is_current=True,
            section="3장 2조",
            page=5,
        )
        assert src.chunk_id == _CHUNK_ID
        assert src.doc_name == "취업규칙"
        assert src.is_current is True

    def test_section_and_page_can_be_none(self) -> None:
        src = Source(
            chunk_id=_CHUNK_ID,
            doc_id=_DOC_ID,
            doc_name="규정",
            version="1.0",
            is_current=False,
            section=None,
            page=None,
        )
        assert src.section is None
        assert src.page is None

    def test_frozen(self) -> None:
        src = Source(
            chunk_id=_CHUNK_ID,
            doc_id=_DOC_ID,
            doc_name="규정",
            version="1.0",
            is_current=True,
            section=None,
            page=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            src.doc_name = "changed"  # type: ignore[misc]


class TestHistory:
    def _make_versions(self) -> tuple[Version, Version]:
        v1 = Version(
            version_id=_VERSION_ID_1,
            version="1.0",
            is_current=False,
            effective_date=date(2022, 1, 1),
            uploaded_at=_NOW,
        )
        v2 = Version(
            version_id=_VERSION_ID_2,
            version="2.1",
            is_current=True,
            effective_date=date(2024, 1, 1),
            uploaded_at=_NOW,
        )
        return v1, v2

    def test_basic_creation(self) -> None:
        v1, v2 = self._make_versions()
        history = History(
            doc_id=_DOC_ID,
            current_version="2.1",
            versions=(v2, v1),
            superseded_by={"1.0": "2.1", "2.1": None},
            conflicts=(),
        )
        assert history.current_version == "2.1"
        assert len(history.versions) == 2

    def test_conflicts_tuple(self) -> None:
        v1, v2 = self._make_versions()
        history = History(
            doc_id=_DOC_ID,
            current_version="2.1",
            versions=(v2, v1),
            superseded_by={"1.0": "2.1", "2.1": None},
            conflicts=(("2.1", "1.0"),),
        )
        assert history.conflicts == (("2.1", "1.0"),)

    def test_frozen(self) -> None:
        v1, v2 = self._make_versions()
        history = History(
            doc_id=_DOC_ID,
            current_version="2.1",
            versions=(v2, v1),
            superseded_by={},
            conflicts=(),
        )
        with pytest.raises((AttributeError, TypeError)):
            history.current_version = "3.0"  # type: ignore[misc]
