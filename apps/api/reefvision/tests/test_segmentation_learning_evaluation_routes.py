"""Schema and route contract: mask evaluation is not deployment."""

from pydantic import ValidationError
import pytest

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
