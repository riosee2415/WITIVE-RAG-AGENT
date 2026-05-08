"""Pipeline job domain models — Job, Stages, JobStatus, StageStatus.

References:
  @docs/03-document-pipeline.md §2.3 (job JSON schema / S3 truth source)
  @docs/03-document-pipeline.md §3.1 (Worker job lifecycle)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class JobStatus(StrEnum):
    """End-to-end pipeline job status.

    Docs: @docs/03-document-pipeline.md §2.3 / §3.6
    """

    QUEUED = "QUEUED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    FAILED_STAGE_A = "FAILED_STAGE_A"
    FAILED_STAGE_B = "FAILED_STAGE_B"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    CLEANED_UP = "CLEANED_UP"
    FAILED_RETRY = "FAILED_RETRY"


class StageStatus(StrEnum):
    """Per-stage status within a job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Stages:
    """Status of each Worker pipeline stage.

    Default value for all stages is ``StageStatus.PENDING`` matching the
    initial job JSON written at upload time.

    Docs: @docs/03-document-pipeline.md §2.3
    """

    parsing: StageStatus = StageStatus.PENDING
    chunking: StageStatus = StageStatus.PENDING
    embedding: StageStatus = StageStatus.PENDING
    indexing: StageStatus = StageStatus.PENDING


@dataclass(frozen=True, slots=True)
class Job:
    """Pipeline job entity persisted as ``s3://…/jobs/{job_id}.json``.

    S3 is the single source of truth; Redis holds a 5-second TTL cache.

    Docs: @docs/03-document-pipeline.md §2.3
    """

    job_id: UUID
    doc_id: UUID
    tenant_id: UUID
    version: str
    status: JobStatus
    created_at: datetime
    s3_path: str
    stages: Stages
    attempts: int = 0
    error: str | None = None
    completed_at: datetime | None = None
    staging_artifact_keys: tuple[str, ...] = field(default=())

    # ------------------------------------------------------------------
    # Serialisation helpers (S3 jobs/{job_id}.json)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the canonical S3 JSON schema.

        All UUID and datetime values are converted to strings for JSON
        compatibility.  The schema must stay in sync with
        @docs/03-document-pipeline.md §2.3.
        """
        return {
            "job_id": str(self.job_id),
            "doc_id": str(self.doc_id),
            "tenant_id": str(self.tenant_id),
            "version": self.version,
            "status": str(self.status),
            "created_at": self.created_at.isoformat(),
            "s3_path": self.s3_path,
            "stages": {
                "parsing": str(self.stages.parsing),
                "chunking": str(self.stages.chunking),
                "embedding": str(self.stages.embedding),
                "indexing": str(self.stages.indexing),
            },
            "attempts": self.attempts,
            "error": self.error,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at is not None else None
            ),
            "staging_artifact_keys": list(self.staging_artifact_keys),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        """Deserialise from the canonical S3 JSON schema.

        Inverse of ``to_dict``.  Raises ``KeyError`` or ``ValueError``
        if required fields are missing or malformed.
        """
        raw_stages: dict[str, str] = data["stages"]
        stages = Stages(
            parsing=StageStatus(raw_stages["parsing"]),
            chunking=StageStatus(raw_stages["chunking"]),
            embedding=StageStatus(raw_stages["embedding"]),
            indexing=StageStatus(raw_stages["indexing"]),
        )
        raw_completed: str | None = data.get("completed_at")
        return cls(
            job_id=UUID(data["job_id"]),
            doc_id=UUID(data["doc_id"]),
            tenant_id=UUID(data["tenant_id"]),
            version=data["version"],
            status=JobStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            s3_path=data["s3_path"],
            stages=stages,
            attempts=int(data.get("attempts", 0)),
            error=data.get("error"),
            completed_at=(
                datetime.fromisoformat(raw_completed) if raw_completed is not None else None
            ),
            staging_artifact_keys=tuple(data.get("staging_artifact_keys", [])),
        )
