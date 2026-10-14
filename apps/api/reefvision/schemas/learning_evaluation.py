"""Frozen holdout comparison and explicit deployment contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reefvision.domain.learning_evaluation import DetectionMetrics


class LearningEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version_id: str
    candidate_model_id: str
    incumbent_model_id: str | None = None
    split: Literal["validation", "test"] = "validation"
    minimum_images: int = Field(default=3, ge=2)
    minimum_objects_per_class: int = Field(default=5, ge=2)
    minimum_ap50: float = Field(default=0.5, ge=0.1, le=1)
    minimum_precision: float = Field(default=0.5, ge=0.1, le=1)
    minimum_recall: float = Field(default=0.5, ge=0.1, le=1)
    minimum_ap50_gain: float = Field(default=0.01, ge=0, le=1)


class LearningEvaluationResponse(BaseModel):
    id: str
    status: str
    candidate_job_id: str
    incumbent_job_id: str | None
    candidate_metrics: DetectionMetrics | None = None
    incumbent_metrics: DetectionMetrics | None = None
    promotion_eligible: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=lambda: [
            "AP50 is an all-points IoU=0.5 box metric, not mask IoU or COCO mAP50:95.",
            "Small holdouts and repeated validation selection can overestimate generalization.",
            "Uncertainty calibration and independent external test evaluation are not provided.",
        ]
    )


class LearningDeploymentResponse(BaseModel):
    id: str
    active_model_id: str | None
    previous_model_id: str | None
    evaluation_id: str | None
