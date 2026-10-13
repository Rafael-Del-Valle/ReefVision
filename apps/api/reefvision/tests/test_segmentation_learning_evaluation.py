"""Scientific regression cases for completed segmentation evaluation records."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, Job
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.domain.segmentation_evaluation import InstanceMaskMetrics
from reefvision.domain.segmentation_holdout import SegmentationHoldout
from reefvision.services.segmentation_learning_evaluation import (
    SegmentationLearningEvaluationService,
)
from reefvision.services.segmentation_scoring import ScoredSegmentationHoldout


def service_with_job(job: Job) -> SegmentationLearningEvaluationService:
    session = Mock()
    session.get.return_value = job
    return SegmentationLearningEvaluationService(session, cast(Settings, Mock()))


def successful_job() -> Job:
    return Job(
        id="job-1",
        project_id="p",
        job_type="inference",
        status="succeeded",
        progress_current=1,
        progress_total=1,
        request_json={
            "model_id": "m",
            "model_task": "segment",
            "evaluation_only": True,
            "image_ids": ["image-1"],
        },
    )


def holdout() -> SegmentationHoldout:
    return SegmentationHoldout("test", ("image-1",), ("colony-1",), ())


def test_completed_evaluation_only_job_passes_preflight() -> None:
    job = successful_job()
    service = service_with_job(job)
    assert service._job("p", "m", "job-1", holdout()) is job


@pytest.mark.parametrize(
    "field,value",
    [
        ("evaluation_only", False),
        ("model_task", "detect"),
        ("model_id", "m2"),
        ("image_ids", ["image-1", "outside"]),
        ("image_ids", ["image-1", "image-1"]),
    ],
)
def test_untrusted_job_payload_fails_closed(field: str, value: Any) -> None:
    job = successful_job()
    job.request_json[field] = value
    with pytest.raises(ConflictError):
        service_with_job(job)._job("p", "m", "job-1", holdout())


def test_queued_or_incomplete_job_is_not_scored() -> None:
    job = successful_job()
    job.status = "running"
    with pytest.raises(ConflictError):
        service_with_job(job)._job("p", "m", "job-1", holdout())
    job.status = "succeeded"
    job.progress_current = 0
    with pytest.raises(ConflictError):
        service_with_job(job)._job("p", "m", "job-1", holdout())


def test_recorded_segmentation_metrics_do_not_activate_model(monkeypatch) -> None:
    from reefvision.services import segmentation_learning_evaluation as module

    mask_holdout = holdout()
    session = Mock()
    version = SimpleNamespace(
        id="v1",
        manifest_sha256="a" * 64,
        class_map_json=[{"id": "class-1"}],
    )
    session.get.side_effect = lambda cls, key: version if cls is DatasetVersion else None
    session.scalars.return_value = [SimpleNamespace(image_id="image-1")]
    monkeypatch.setattr(
        module.SegmentationHoldoutService,
        "prepare",
        lambda _self, *_args, **_kwargs: mask_holdout,
    )
    metrics = InstanceMaskMetrics(
        mask_map50=0.9,
        precision=1.0,
        recall=1.0,
        count_bias_per_image=0.0,
        mean_absolute_count_error=0.0,
        mean_matched_mask_iou=1.0,
        per_class={},
    )
    scored = ScoredSegmentationHoldout("v1", "a" * 64, "test", "job-1", "m", "b" * 64, metrics)
    service = SegmentationLearningEvaluationService(session, cast(Settings, Mock()))
    monkeypatch.setattr(service, "_score_model", lambda *_args, **_kwargs: scored)
    record = service.record_completed_evaluation(
        "p",
        "v1",
        split="test",
        candidate_model_id="m",
        candidate_job_id="job-1",
        minimum_mask_map50=0.7,
    )
    assert record.job_type == "segmentation_learning_evaluation"
    assert record.result_json["promotion_eligible"] is True
    assert record.request_json["manifest_sha256"] == "a" * 64
    assert record.request_json["candidate_checksum"] == "b" * 64
    assert "active_model_id" not in record.result_json
    session.add.assert_called_once_with(record)
    session.commit.assert_called_once()


def test_quality_floor_blocks_promotion_eligibility(monkeypatch) -> None:
    from reefvision.services import segmentation_learning_evaluation as module

    session = Mock()
    session.get.return_value = SimpleNamespace(
        id="v1",
        manifest_sha256="a" * 64,
        class_map_json=[{"id": "class-1"}],
    )
    session.scalars.return_value = []
    monkeypatch.setattr(
        module.SegmentationHoldoutService,
        "prepare",
        lambda _self, *_args, **_kwargs: holdout(),
    )
    metrics = InstanceMaskMetrics(0.3, 0, 0, -1, 1, 0, {})
    scored = ScoredSegmentationHoldout("v1", "a" * 64, "test", "job-1", "m", "b" * 64, metrics)
    service = SegmentationLearningEvaluationService(session, cast(Settings, Mock()))
    monkeypatch.setattr(service, "_score_model", lambda *_args, **_kwargs: scored)
    record = service.record_completed_evaluation(
        "p", "v1", split="test", candidate_model_id="m", candidate_job_id="job-1"
    )
    assert record.result_json["promotion_eligible"] is False
    assert record.result_json["blockers"]


def test_incumbent_model_and_job_cannot_be_supplied_separately() -> None:
    service = SegmentationLearningEvaluationService(Mock(), cast(Settings, Mock()))
    with pytest.raises(ValidationError, match="together"):
        service.record_completed_evaluation(
            "p",
            "v",
            split="test",
            candidate_model_id="candidate",
            candidate_job_id="candidate-job",
            incumbent_model_id="incumbent",
        )
