"""Scientist-controlled learning from reviewed project annotations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reefvision.schemas.dataset_versions import DatasetVersionResponse
from reefvision.schemas.training import TrainingPreflightResponse, TrainingRunResponse


class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: Literal["detect", "segment"] = "detect"
    minimum_images: int = Field(default=10, ge=2, le=100000)
    minimum_objects_per_class: int = Field(default=20, ge=2, le=1000000)
    validation_fraction: float = Field(default=0.2, ge=0.1, le=0.5)
    seed: int = 42
    architecture: str | None = Field(default=None, max_length=200)
    initial_checkpoint_model_id: str | None = Field(default=None, max_length=36)
    epochs: int = Field(default=20, ge=1, le=500)
    batch: int = Field(default=2, ge=1, le=64)
    imgsz: int = Field(default=640, ge=32, le=2048, multiple_of=32)
    device: Literal["cpu", "auto"] = "cpu"


class LearningClassCount(BaseModel):
    label_class_id: str
    class_name: str
    count: int
    train_count: int
    validation_count: int


class LearningStatus(BaseModel):
    ready: bool
    config: LearningConfig
    blockers: list[str]
    warnings: list[str]
    reviewed_image_count: int
    eligible_object_count: int
    per_class_counts: list[LearningClassCount]
    split_counts: dict[str, int]
    latest_run: TrainingRunResponse | None = None
    active_model_id: str | None = None
    promotion_policy: str = (
        "Candidate only; held-out evaluation and explicit model selection required."
    )


class LearningImproveResponse(BaseModel):
    readiness: LearningStatus
    dataset_version: DatasetVersionResponse | None = None
    run: TrainingRunResponse | None = None
    preflight: TrainingPreflightResponse | None = None
