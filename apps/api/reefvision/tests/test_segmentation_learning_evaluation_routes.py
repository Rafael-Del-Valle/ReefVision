"""Schema and route contract: mask evaluation is not deployment."""

import pytest
from pydantic import ValidationError

from reefvision.api.routes.segmentation_learning_evaluation import router
from reefvision.schemas.segmentation_learning_evaluation import (
    SegmentationCompletedEvaluationRequest,
)


def test_segmentation_evaluation_requires_explicit_completed_job_identity() -> None:
    with pytest.raises(ValidationError):
        SegmentationCompletedEvaluationRequest(
            dataset_version_id="v",
            candidate_model_id="m",
        )
    with pytest.raises(ValidationError):
        SegmentationCompletedEvaluationRequest(
            dataset_version_id="v",
            candidate_model_id="m",
            candidate_job_id="j",
            split="train",
        )


def test_segmentation_api_never_exposes_implicit_deployment() -> None:
    paths = {route.path for route in router.routes}
    assert "/projects/{project_id}/learning/segmentation/evaluations" in paths
    assert "/projects/{project_id}/learning/segmentation/evaluations/{evaluation_id}" in paths
    assert not any("promote" in path or "rollback" in path for path in paths)


def test_waiting_segmentation_evaluation_has_no_premature_metrics() -> None:
    from reefvision.api.routes.segmentation_learning_evaluation import _response
    from reefvision.db.models import Job

    queued = Job(
        id="queue-1",
        project_id="project-1",
        job_type="segmentation_learning_evaluation",
        status="waiting",
        request_json={
            "dataset_version_id": "dataset-1",
            "manifest_sha256": "a" * 64,
            "split": "validation",
            "candidate_model_id": "candidate",
            "candidate_job_id": "job-2",
            "candidate_checksum": "b" * 64,
            "incumbent_model_id": None,
            "incumbent_job_id": None,
            "incumbent_checksum": None,
        },
        result_json={"promotion_eligible": False, "blockers": ["Waiting for inference"]},
    )
    result = _response(queued)
    assert result.status == "waiting"
    assert result.candidate_metrics is None
    assert result.promotion_eligible is False
    assert "Waiting for inference" in result.blockers
