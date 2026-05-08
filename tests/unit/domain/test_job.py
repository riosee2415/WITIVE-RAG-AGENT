"""Unit tests for app.domain.job."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain.job import Job, JobStatus, Stages, StageStatus

_JOB_ID = UUID("11111111-0000-0000-0000-000000000001")
_DOC_ID = UUID("22222222-0000-0000-0000-000000000001")
_TENANT_ID = UUID("33333333-0000-0000-0000-000000000001")
_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "job_id": _JOB_ID,
        "doc_id": _DOC_ID,
        "tenant_id": _TENANT_ID,
        "version": "1.0",
        "status": JobStatus.QUEUED,
        "created_at": _NOW,
        "s3_path": "s3://witive-docs/tenant/jobs/job.json",
        "stages": Stages(),
        "attempts": 0,
        "error": None,
        "completed_at": None,
        "staging_artifact_keys": (),
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JobStatus enum
# ---------------------------------------------------------------------------


class TestJobStatus:
    def test_expected_values(self) -> None:
        assert JobStatus.QUEUED == "QUEUED"
        assert JobStatus.PARSING == "PARSING"
        assert JobStatus.CHUNKING == "CHUNKING"
        assert JobStatus.EMBEDDING == "EMBEDDING"
        assert JobStatus.INDEXING == "INDEXING"
        assert JobStatus.COMPLETED == "COMPLETED"
        assert JobStatus.FAILED == "FAILED"
        assert JobStatus.FAILED_STAGE_A == "FAILED_STAGE_A"
        assert JobStatus.FAILED_STAGE_B == "FAILED_STAGE_B"
        assert JobStatus.PARTIAL_SUCCESS == "PARTIAL_SUCCESS"
        assert JobStatus.CLEANED_UP == "CLEANED_UP"
        assert JobStatus.FAILED_RETRY == "FAILED_RETRY"

    def test_twelve_statuses_defined(self) -> None:
        assert len(JobStatus) == 12


# ---------------------------------------------------------------------------
# Stages defaults
# ---------------------------------------------------------------------------


class TestStages:
    def test_all_default_pending(self) -> None:
        s = Stages()
        assert s.parsing is StageStatus.PENDING
        assert s.chunking is StageStatus.PENDING
        assert s.embedding is StageStatus.PENDING
        assert s.indexing is StageStatus.PENDING

    def test_custom_stages(self) -> None:
        s = Stages(parsing=StageStatus.DONE, chunking=StageStatus.RUNNING)
        assert s.parsing is StageStatus.DONE
        assert s.chunking is StageStatus.RUNNING

    def test_frozen(self) -> None:
        s = Stages()
        with pytest.raises((AttributeError, TypeError)):
            s.parsing = StageStatus.DONE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Job to_dict / from_dict roundtrip
# ---------------------------------------------------------------------------


class TestJobRoundtrip:
    def test_basic_roundtrip(self) -> None:
        job = _job()
        data = job.to_dict()
        restored = Job.from_dict(data)
        assert restored.job_id == job.job_id
        assert restored.doc_id == job.doc_id
        assert restored.tenant_id == job.tenant_id
        assert restored.version == job.version
        assert restored.status is job.status
        assert restored.created_at == job.created_at
        assert restored.s3_path == job.s3_path
        assert restored.attempts == job.attempts
        assert restored.error == job.error
        assert restored.completed_at is None
        assert restored.staging_artifact_keys == ()

    def test_roundtrip_with_completed_at(self) -> None:
        completed = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)
        job = _job(status=JobStatus.COMPLETED, completed_at=completed)
        restored = Job.from_dict(job.to_dict())
        assert restored.completed_at == completed

    def test_roundtrip_with_error(self) -> None:
        job = _job(status=JobStatus.FAILED, error="PARSE_ERROR")
        restored = Job.from_dict(job.to_dict())
        assert restored.error == "PARSE_ERROR"

    def test_roundtrip_with_staging_artifact_keys(self) -> None:
        keys = ("stg:job1:0", "stg:job1:1")
        job = _job(
            status=JobStatus.FAILED_STAGE_A,
            staging_artifact_keys=keys,
        )
        restored = Job.from_dict(job.to_dict())
        assert restored.staging_artifact_keys == keys

    def test_to_dict_types(self) -> None:
        job = _job()
        d = job.to_dict()
        assert isinstance(d["job_id"], str)
        assert isinstance(d["doc_id"], str)
        assert isinstance(d["tenant_id"], str)
        assert isinstance(d["created_at"], str)
        assert isinstance(d["stages"], dict)
        assert d["completed_at"] is None
        assert isinstance(d["staging_artifact_keys"], list)

    def test_stages_roundtrip(self) -> None:
        stages = Stages(
            parsing=StageStatus.DONE,
            chunking=StageStatus.DONE,
            embedding=StageStatus.RUNNING,
            indexing=StageStatus.PENDING,
        )
        job = _job(stages=stages)
        restored = Job.from_dict(job.to_dict())
        assert restored.stages.parsing is StageStatus.DONE
        assert restored.stages.chunking is StageStatus.DONE
        assert restored.stages.embedding is StageStatus.RUNNING
        assert restored.stages.indexing is StageStatus.PENDING


# ---------------------------------------------------------------------------
# Job frozen
# ---------------------------------------------------------------------------


class TestJobFrozen:
    def test_frozen(self) -> None:
        job = _job()
        with pytest.raises((AttributeError, TypeError)):
            job.status = JobStatus.COMPLETED  # type: ignore[misc]
