"""Document domain models — Document, Version, Chunk.

References:
  @docs/04-data-stores.md §2.2 (Neo4j node schema)
  @docs/04-data-stores.md §1.3 (Pinecone metadata schema)
  @docs/03-document-pipeline.md §3.3 (Chunk output domain)
  @docs/03-document-pipeline.md §2.1 (access_level field coherence rules)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.domain.access import AccessLevel, Level


@dataclass(frozen=True, slots=True)
class Document:
    """Persistent document entity mirroring the Neo4j Document node.

    Field-level coherence rules (validated in ``__post_init__``):
    - ``DEPARTMENT``  → ``allowed_departments`` must be non-empty.
    - ``LEVEL``       → ``allowed_levels`` must be non-empty.
    - ``EXECUTIVE``   → ``allowed_user_ids`` must be non-empty.
    - ``COMPANY_WIDE``→ all ``allowed_*`` collections should be empty
                        (not enforced as error; extra data is harmless).

    Docs: @docs/03-document-pipeline.md §2.1
    """

    doc_id: UUID
    doc_name: str
    tenant_id: UUID
    access_level: AccessLevel
    allowed_departments: tuple[str, ...]
    allowed_levels: tuple[Level, ...]
    min_level_rank: int | None
    allowed_user_ids: tuple[UUID, ...]
    archived: bool
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate access-level field coherence."""
        if not self.doc_name or len(self.doc_name) > 256:
            raise ValueError(f"doc_name must be 1-256 chars, got {len(self.doc_name)!r}")
        if self.access_level is AccessLevel.DEPARTMENT and not self.allowed_departments:
            raise ValueError("allowed_departments must be non-empty when access_level=DEPARTMENT")
        if self.access_level is AccessLevel.LEVEL and not self.allowed_levels:
            raise ValueError("allowed_levels must be non-empty when access_level=LEVEL")
        if self.access_level is AccessLevel.EXECUTIVE and not self.allowed_user_ids:
            raise ValueError("allowed_user_ids must be non-empty when access_level=EXECUTIVE")


@dataclass(frozen=True, slots=True)
class Version:
    """A specific version of a document.

    Mirrors the Neo4j Version node.
    Docs: @docs/04-data-stores.md §2.2
    """

    version_id: UUID
    version: str
    is_current: bool
    effective_date: date
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class Chunk:
    """A single text chunk produced by the chunking stage.

    ``embedding_id`` keeps the chunk in sync with its Pinecone vector_id.
    ``staging`` mirrors Neo4j ``Chunk.staging`` — only ``false`` chunks
    appear in search results.

    Docs:
      @docs/03-document-pipeline.md §3.3
      @docs/04-data-stores.md §2.2 (Neo4j Chunk node)
      @docs/04-data-stores.md §1.3 (Pinecone meta schema)
    """

    chunk_id: UUID
    text: str
    section: str | None
    section_number: str | None
    page: int | None
    chunk_index: int
    embedding_id: str
    char_range: tuple[int, int]
    staging: bool = field(default=False)
