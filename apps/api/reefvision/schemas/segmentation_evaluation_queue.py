"""Explicit queued segmentation holdout evaluation, without automatic deployment."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentationEvaluationQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: str = Field(min_length=1)
    candidate_model_id: str = Field(min_length=1)
    incumbent_model_id: str | None = None
    split: Literal["validation", "test"] = "validation"
    minimum_images: int = Field(default=2, ge=2)
    minimum_masks: int = Field(default=2, ge=2)
    minimum_mask_map50: float = Field(default=0.5, ge=0, le=1)
    minimum_gain: float = Field(default=0.0, ge=0, le=1)
