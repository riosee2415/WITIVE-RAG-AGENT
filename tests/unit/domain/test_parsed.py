"""Unit tests for app.domain.parsed."""

from __future__ import annotations

import pytest

from app.domain.parsed import Page, ParsedDocument, Section


class TestSection:
    def test_basic_creation(self) -> None:
        s = Section(title="제1장 총칙", number="제1장", start=0, end=200)
        assert s.title == "제1장 총칙"
        assert s.number == "제1장"
        assert s.start == 0
        assert s.end == 200

    def test_number_can_be_none(self) -> None:
        s = Section(title="서론", number=None, start=0, end=50)
        assert s.number is None

    def test_frozen(self) -> None:
        s = Section(title="제1장", number=None, start=0, end=10)
        with pytest.raises((AttributeError, TypeError)):
            s.title = "changed"  # type: ignore[misc]


class TestPage:
    def test_basic_creation(self) -> None:
        p = Page(page_number=1, start=0, end=500)
        assert p.page_number == 1

    def test_frozen(self) -> None:
        p = Page(page_number=1, start=0, end=100)
        with pytest.raises((AttributeError, TypeError)):
            p.page_number = 2  # type: ignore[misc]


class TestParsedDocument:
    def test_basic_creation(self) -> None:
        doc = ParsedDocument(text="본문 내용", sections=(), pages=())
        assert doc.text == "본문 내용"
        assert doc.warnings == ()

    def test_with_sections_and_pages(self) -> None:
        sec = Section(title="제1장", number="제1장", start=0, end=100)
        pg = Page(page_number=1, start=0, end=100)
        doc = ParsedDocument(text="내용", sections=(sec,), pages=(pg,))
        assert len(doc.sections) == 1
        assert len(doc.pages) == 1

    def test_warnings_default_empty(self) -> None:
        doc = ParsedDocument(text="x", sections=(), pages=())
        assert doc.warnings == ()

    def test_warnings_can_be_set(self) -> None:
        doc = ParsedDocument(
            text="x",
            sections=(),
            pages=(),
            warnings=("OCR_FALLBACK",),
        )
        assert "OCR_FALLBACK" in doc.warnings

    def test_frozen(self) -> None:
        doc = ParsedDocument(text="x", sections=(), pages=())
        with pytest.raises((AttributeError, TypeError)):
            doc.text = "y"  # type: ignore[misc]
