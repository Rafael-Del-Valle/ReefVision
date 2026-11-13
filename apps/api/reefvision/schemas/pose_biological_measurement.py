"""Contracts for anatomical measurements and biological events."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


MeasurementKind = Literal["distance", "angle", "displacement", "velocity", "direction", "angular_velocity", "curvature", "body_axis_orientation", "relative_movement", "extension"]


class MeasurementDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: MeasurementKind
    landmark_ids: list[str] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_landmarks(self) -> "MeasurementDefinition":
        required = {"distance": 2, "angle": 3, "body_axis_orientation": 2, "curvature": 3}
        if len(self.landmark_ids) < required.get(self.kind, 1):
            raise ValueError(f"{self.kind} requires at least {required[self.kind]} landmarks")
        if len(set(self.landmark_ids)) != len(self.landmark_ids):
            raise ValueError("landmark_ids must be unique")
        return self


class PoseMeasurementRunCreateRequest(BaseModel):
    video_id: str
    source_identity_run_id: str
    source_identity_run_revision: int = Field(ge=1)
    identity_ids: list[str] = Field(default_factory=list)
    definitions: list[MeasurementDefinition] = Field(min_length=1)
    maximum_gap_s: float = Field(default=0.25, ge=0)
    verification_mode: Literal["exploratory", "scientific"] = "exploratory"


class CycleDefinition(BaseModel):
    measurement_series_id: str
    open_threshold: float
    close_threshold: float
    minimum_amplitude: float = Field(default=0, ge=0)
    minimum_duration_s: float = Field(default=0, ge=0)
    maximum_duration_s: float | None = Field(default=None, gt=0)
    minimum_separation_s: float = Field(default=0, ge=0)
    refractory_s: float = Field(default=0, ge=0)
    minimum_confidence: float = Field(default=0, ge=0, le=1)
    maximum_gap_s: float = Field(default=0.25, ge=0)
    smoothing: Literal["none", "mean", "median"] = "none"
    smoothing_window: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_hysteresis(self) -> "CycleDefinition":
        if self.open_threshold <= self.close_threshold:
            raise ValueError("open_threshold must exceed close_threshold")
        if self.maximum_duration_s is not None and self.maximum_duration_s < self.minimum_duration_s:
            raise ValueError("maximum_duration_s must be >= minimum_duration_s")
        return self


class EventCorrectionRequest(BaseModel):
    action: Literal["confirm", "reject", "adjust_boundaries", "remove", "add"]
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="local_user", min_length=1, max_length=100)


class BiologicalMovementExportRequest(BaseModel):
    reviewed_only: bool = True
    format: Literal["json", "csv_zip"] = "json"
