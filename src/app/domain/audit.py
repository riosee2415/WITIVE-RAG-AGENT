"""Provenance / audit domain models — Source, History.

Used to track chunk origins in RAG answers and document version chains.

References:
  @docs/04-data-stores.md §2.2 (Neo4j Version relationships)
  @docs/03-document-pipeline.md §3.7 (conflict detection)
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.document import Version


@dataclass(frozen=True, slots=True)
class Source:
    """Provenance record for a single chunk used in a RAG answer.

    Surfaced in the SSE ``sources`` event so that the UI can link each
    answer sentence back to the originating document version and section.

    Docs: @docs/06-api.md §3.1 (Source response schema)
    """

    chunk_id: UUID
    doc_id: UUID
    doc_name: str
    version: str
    is_current: bool
    section: str | None
    page: int | None


@dataclass(frozen=True, slots=True)
class History:
    """Version chain for a single document.

    ``superseded_by`` maps each version string to the newer version string
    that superseded it (``None`` if this is the latest version).

    ``conflicts`` contains pairs of ``(new_version, old_version)`` for
    automatically detected conflicting article revisions produced by the
    ``CONFLICTS_WITH`` Neo4j relationship (§3.7).

    Docs: @docs/04-data-stores.md §2.2, @docs/03-document-pipeline.md §3.7
    """

    doc_id: UUID
    current_version: str
    versions: tuple[Version, ...]
    superseded_by: dict[str, str | None]
    conflicts: tuple[tuple[str, str], ...]
