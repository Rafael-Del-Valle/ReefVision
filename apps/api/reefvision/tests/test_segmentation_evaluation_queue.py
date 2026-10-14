"""Queueing safeguards: isolated inference, source holdout, and idempotent completion."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, Job
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.domain.segmentation_holdout import SegmentationHoldout
from reefvision.schemas.segmentation_evaluation_queue import SegmentationEvaluationQueueRequest
from reefvision.services.segmentation_evaluation_queue import SegmentationEvaluationQueueService


def setup_service(monkeypatch) -> tuple[SegmentationEvaluationQueueService, Mock, dict[str, Job]]:
    from reefvision.services import segmentation_evaluation_queue as module

    session = Mock()
    jobs: dict[str, Job] = {}
    version = SimpleNamespace(id="dataset-1", manifest_sha256="a" * 64)
    session.get.side_effect = lambda cls, key: version if cls is DatasetVersion else jobs.get(key)
    holdout = SegmentationHoldout("validation", ("img-a", "img-b"), ("group-a", "group-b"), ())
    monkeypatch.setattr(
        module.SegmentationHoldoutService,
        "prepare",
        lambda *_args, **_kwargs: holdout,
    )
    service = SegmentationEvaluationQueueService(session, cast(Settings, Mock()))
    monkeypatch.setattr(
        service.scoring,
        "_model",
        lambda _project, model_id, *_args, **_kw: SimpleNamespace(id=model_id, sha256="b" * 64),
    )
    serial = 0

    def flush() -> None:
        nonlocal serial
        for call in session.add.call_args_list:
            job = call.args[0]
            if job.id is None:
                serial += 1
                job.id = f"job-{serial}"
                jobs[job.id] = job

    session.flush.side_effect = flush
    return service, session, jobs


def queue(service: SegmentationEvaluationQueueService, **extra: Any) -> Job:
    options: dict[str, Any] = {
        "split": "validation",
        "candidate_model_id": "candidate",
        "minimum_images": 2,
        "minimum_masks": 2,
    }
    options.update(extra)
    return service.queue("project-1", "dataset-1", **options)


def test_queue_makes_evaluation_only_jobs_for_same_verified_holdout(monkeypatch) -> None:
    service, session, jobs = setup_service(monkeypatch)
    record = queue(service, incumbent_model_id="incumbent")
    assert record.status == "waiting"
    assert record.progress_total == 2
    assert record.request_json["candidate_job_id"] in jobs
    assert record.request_json["incumbent_job_id"] in jobs
    assert record.request_json["heldout_image_ids"] == ["img-a", "img-b"]
    for key, model_id in [
        ("candidate_job_id", "candidate"),
        ("incumbent_job_id", "incumbent"),
    ]:
        child = jobs[record.request_json[key]]
        assert child.status == "queued"
        assert child.job_type == "inference"
        assert child.request_json["model_id"] == model_id
        assert child.request_json["model_task"] == "segment"
        assert child.request_json["evaluation_only"] is True
        assert child.request_json["image_ids"] == ["img-a", "img-b"]
        assert child.request_json["segmentation_holdout_parent_job_id"] == record.id
        assert child.request_json["segmentation_manifest_sha256"] == "a" * 64
        assert child.request_json["segmentation_dataset_version_id"] == "dataset-1"
        assert child.request_json["segmentation_split"] == "validation"
        assert child.request_json["segmentation_checkpoint_sha256"] == "b" * 64
    session.commit.assert_called_once()


def test_queue_refuses_same_model_as_incumbent(monkeypatch) -> None:
    service, session, _jobs = setup_service(monkeypatch)
    with pytest.raises(ValidationError, match="different"):
        queue(service, incumbent_model_id="candidate")
    session.add.assert_not_called()


def test_waiting_children_cannot_be_evaluated(monkeypatch) -> None:
    service, session, _jobs = setup_service(monkeypatch)
    parent = queue(service)
    service.scoring.record_completed_evaluation = Mock()
    result = service.advance("project-1", parent.id)
    assert result.status == "waiting"
    assert result.progress_current == 0
    service.scoring.record_completed_evaluation.assert_not_called()
    assert session.commit.call_count == 2


def test_completed_children_finalize_same_parent_once(monkeypatch) -> None:
    service, _session, jobs = setup_service(monkeypatch)
    parent = queue(service, incumbent_model_id="incumbent")
    for key in ("candidate_job_id", "incumbent_job_id"):
        jobs[parent.request_json[key]].status = "succeeded"

    def finalized(*_args: Any, **kwargs: Any) -> Job:
        assert kwargs["existing_record"] is parent
        assert kwargs["candidate_model_id"] == "candidate"
        assert kwargs["incumbent_model_id"] == "incumbent"
        parent.status = "completed"
        return parent

    service.scoring.record_completed_evaluation = Mock(side_effect=finalized)
    assert service.advance("project-1", parent.id) is parent
    assert parent.status == "completed"
    service.scoring.record_completed_evaluation.assert_called_once()
    assert service.advance("project-1", parent.id) is parent
    service.scoring.record_completed_evaluation.assert_called_once()


def test_cancelled_child_fails_closed_with_no_promotion(monkeypatch) -> None:
    service, session, jobs = setup_service(monkeypatch)
    parent = queue(service)
    jobs[parent.request_json["candidate_job_id"]].status = "cancelled"
    service.scoring.record_completed_evaluation = Mock()
    result = service.advance("project-1", parent.id)
    assert result.status == "failed"
    assert result.result_json["promotion_eligible"] is False
    assert result.completed_at is not None
    service.scoring.record_completed_evaluation.assert_not_called()
    assert session.commit.call_count == 2


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("evaluation_only", False),
        ("model_id", "other-candidate"),
        ("segmentation_checkpoint_sha256", "0" * 64),
        ("segmentation_dataset_version_id", "different-dataset"),
        ("segmentation_split", "test"),
        ("segmentation_manifest_sha256", "c" * 64),
        ("segmentation_holdout_parent_job_id", "different-parent"),
        ("image_ids", ["img-a"]),
    ],
)
def test_altered_child_provenance_rejected(monkeypatch, field: str, tampered: Any) -> None:
    service, _session, jobs = setup_service(monkeypatch)
    parent = queue(service)
    job = jobs[parent.request_json["candidate_job_id"]]
    job.status = "succeeded"
    job.request_json = {**job.request_json, field: tampered}
    service.scoring.record_completed_evaluation = Mock()
    with pytest.raises(ConflictError, match="no longer matches"):
        service.advance("project-1", parent.id)
    service.scoring.record_completed_evaluation.assert_not_called()


def test_invalid_queue_split_and_support_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        SegmentationEvaluationQueueRequest(
            dataset_version_id="dataset-1",
            candidate_model_id="candidate",
            split="train",
        )
    with pytest.raises(PydanticValidationError):
        SegmentationEvaluationQueueRequest(
            dataset_version_id="dataset-1",
            candidate_model_id="candidate",
            minimum_images=1,
        )
