"""Parsed document domain models — output of the parsing stage.

References:
  @docs/03-document-pipeline.md §3.2 (ParsedDocument schema)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Section:
    """A structural section within a parsed document.

    ``start`` and ``end`` are character offsets into ``ParsedDocument.text``.

    Docs: @docs/03-document-pipeline.md §3.2
    """

    title: str
    number: str | None
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Page:
    """Maps a character range in ``ParsedDocument.text`` to a page number.

    ``start`` and ``end`` are character offsets (inclusive on ``start``,
    exclusive on ``end`` follows Python slice convention).

    Docs: @docs/03-document-pipeline.md §3.2
    """

    page_number: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalised output produced by any parser (PDF / DOCX / XLSX / URL).

    ``text`` is the full normalised text with sections joined by ``\\n\\n``.
    ``warnings`` accumulates non-fatal parse signals such as
    ``OCR_FALLBACK`` or ``OCR_LOW_CONFIDENCE``.

    Docs: @docs/03-document-pipeline.md §3.2
    """

    text: str
    sections: tuple[Section, ...]
    pages: tuple[Page, ...]
    warnings: tuple[str, ...] = field(default=())
