"""Explicit mask-metric evaluation records without model activation."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentationCompletedEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: str = Field(min_length=1)
    candidate_model_id: str = Field(min_length=1)
    candidate_job_id: str = Field(min_length=1)
    incumbent_model_id: str | None = None
    incumbent_job_id: str | None = None
    split: Literal["validation", "test"] = "validation"
    minimum_images: int = Field(default=2, ge=1)
    minimum_masks: int = Field(default=2, ge=1)
    minimum_mask_map50: float = Field(default=0.5, ge=0, le=1)
    minimum_gain: float = Field(default=0.0, ge=0, le=1)


class SegmentationCompletedEvaluationResponse(BaseModel):
    id: str
    status: str
    task: Literal["segment"] = "segment"
    dataset_version_id: str
    manifest_sha256: str
    split: Literal["validation", "test"]
    candidate_model_id: str
    candidate_job_id: str
    candidate_checksum: str
    incumbent_model_id: str | None = None
    incumbent_job_id: str | None = None
    incumbent_checksum: str | None = None
    candidate_metrics: dict[str, Any]
    incumbent_metrics: dict[str, Any] | None = None
    promotion_eligible: bool
    blockers: list[str] = Field(default_factory=list)
    warning: str = (
        "Source-pixel instance mask AP50 is not detector box AP or COCO mask AP50:95. "
        "Eligibility does not activate or promote any model."
    )
