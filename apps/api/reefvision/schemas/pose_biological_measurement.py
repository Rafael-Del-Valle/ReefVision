"""Contracts for anatomical measurements and biological events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MeasurementKind = Literal[
    "distance",
    "angle",
    "displacement",
    "velocity",
    "direction",
    "angular_velocity",
    "curvature",
    "body_axis_orientation",
    "relative_movement",
    "extension",
]


class MeasurementDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: MeasurementKind
    landmark_ids: list[str] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_landmarks(self) -> MeasurementDefinition:
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
    def validate_hysteresis(self) -> CycleDefinition:
        if self.open_threshold <= self.close_threshold:
            raise ValueError("open_threshold must exceed close_threshold")
        if (
            self.maximum_duration_s is not None
            and self.maximum_duration_s < self.minimum_duration_s
        ):
            raise ValueError("maximum_duration_s must be >= minimum_duration_s")
        return self


class EventCorrectionRequest(BaseModel):
    action: Literal["confirm", "reject", "adjust_boundaries", "remove", "add"]
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="local_user", min_length=1, max_length=100)


class ManualEventCreateRequest(BaseModel):
    measurement_series_id: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    cycle_state: Literal["complete", "partial_start", "partial_end", "partial_gap"] = "complete"
    reason: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="local_user", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_frame_order(self) -> ManualEventCreateRequest:
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class BiologicalMovementExportRequest(BaseModel):
    reviewed_only: bool = True
    format: Literal["json", "csv_zip"] = "json"


class EventDetectionCreateRequest(BaseModel):
    measurement_run_id: str
    cycles: list[CycleDefinition] = Field(min_length=1)


class MeasurementRunResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    project_id: str
    video_id: str
    source_identity_run_id: str
    source_identity_run_revision: int
    source_job_id: str | None
    definitions_json: list[dict[str, Any]]
    configuration_json: dict[str, Any]
    status: str
    progress_json: dict[str, Any]
    verification_state: str
    result_sha256: str | None


class EventDetectionRunResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    measurement_run_id: str
    source_job_id: str | None
    configuration_json: dict[str, Any]
    status: str
    progress_json: dict[str, Any]
    result_sha256: str | None


class MeasurementSeriesResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    measurement_run_id: str
    animal_identity_id: str
    definition_id: str
    measurement_kind: str
    display_name: str
    pixel_unit: str
    physical_unit: str | None
    summary_json: dict[str, Any]


class MeasurementSampleResponse(BaseModel):
    model_config = {"from_attributes": True}
    frame_index: int
    time_s: float
    pixel_value: float | None
    physical_value: float | None
    confidence: float | None
    valid: bool
    quality_flags_json: list[str]


class BiologicalEventResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    event_series_id: str
    revision: int
    measurement_series_id: str
    animal_identity_id: str
    start_frame: int
    peak_frame: int | None
    end_frame: int | None
    amplitude: float | None
    duration_s: float | None
    confidence: float | None
    cycle_state: str
    review_state: str
    detection_source: str
    is_current: bool
