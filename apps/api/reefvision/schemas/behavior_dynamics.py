"""Behavior ethogram, bout, and dynamics schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator, model_validator

BehaviorBoutSource = Literal["manual", "imported"]
BehaviorReviewStatus = Literal["verified", "unreviewed"]
BehaviorProvenanceStatus = Literal["current", "stale"]


class BehaviorStateDefinitionInput(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    channel: str = Field(default="primary", min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class BehaviorEthogramCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    states: list[BehaviorStateDefinitionInput] = Field(min_length=1, max_length=500)

    @field_validator("states")
    @classmethod
    def unique_codes(
        cls,
        value: list[BehaviorStateDefinitionInput],
    ) -> list[BehaviorStateDefinitionInput]:
        codes = [item.code.strip().casefold() for item in value]
        if len(codes) != len(set(codes)):
            raise ValueError("Behavior state codes must be unique within an ethogram revision")
        return value


class BehaviorStateDefinitionResponse(BaseModel):
    id: str
    ethogram_revision_id: str
    code: str
    label: str
    channel: str
    description: str | None
    sort_order: int

    model_config = {"from_attributes": True}


class BehaviorEthogramResponse(BaseModel):
    id: str
    ethogram_series_id: str
    project_id: str
    revision: int
    supersedes_revision_id: str | None
    name: str
    description: str | None
    definition_sha256: str
    created_by: str
    created_at: datetime
    states: list[BehaviorStateDefinitionResponse]


class BehaviorBoutCreateRequest(BaseModel):
    ethogram_revision_id: str = Field(min_length=1, max_length=36)
    behavior_state_id: str = Field(min_length=1, max_length=36)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    source: BehaviorBoutSource = "manual"
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_frames_and_confidence(self) -> BehaviorBoutCreateRequest:
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be greater than or equal to start_frame")
        if self.source == "manual" and self.confidence is not None:
            raise ValueError("Manual behavior bouts do not use model confidence")
        return self


class BehaviorBoutResponse(BaseModel):
    id: str
    bout_series_id: str
    revision: int
    supersedes_bout_id: str | None
    video_track_id: str
    ethogram_revision_id: str
    behavior_state_id: str
    behavior_code: str
    behavior_label: str
    channel: str
    start_frame: int
    end_frame: int
    start_time_seconds: float
    end_time_seconds: float
    duration_seconds: float
    source: str
    confidence: float | None
    review_status: str
    source_track_revision: int
    stale_against_track: bool
    revision_reason: str
    note: str | None
    created_by: str
    created_at: datetime


class BehaviorDynamicsRequest(BaseModel):
    ethogram_revision_id: str = Field(min_length=1, max_length=36)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> BehaviorDynamicsRequest:
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class BehaviorStateDynamics(BaseModel):
    behavior_state_id: str
    behavior_code: str
    behavior_label: str
    channel: str
    bout_count: int = Field(ge=0)
    dwell_frames: int = Field(ge=0)
    dwell_seconds: float = Field(ge=0)
    fraction_of_evaluated_time: float = Field(ge=0, le=1)
    fraction_of_labeled_time: float = Field(ge=0, le=1)
    mean_bout_seconds: float | None = Field(default=None, ge=0)
    maximum_bout_seconds: float | None = Field(default=None, ge=0)


class BehaviorTransitionDynamics(BaseModel):
    channel: str
    from_behavior_state_id: str
    from_behavior_code: str
    to_behavior_state_id: str
    to_behavior_code: str
    count: int = Field(ge=1)
    probability_from_state: float = Field(ge=0, le=1)


class BehaviorChannelDynamics(BaseModel):
    channel: str
    evaluated_frames: int = Field(ge=1)
    evaluated_seconds: float = Field(gt=0)
    labeled_frames: int = Field(ge=0)
    labeled_seconds: float = Field(ge=0)
    unlabeled_frames: int = Field(ge=0)
    unlabeled_seconds: float = Field(ge=0)
    coverage_fraction: float = Field(ge=0, le=1)
    states: list[BehaviorStateDynamics]
    transitions: list[BehaviorTransitionDynamics]


class BehaviorDynamicsResponse(BaseModel):
    schema_version: Literal["behavior-dynamics-0001"] = "behavior-dynamics-0001"
    track_id: str
    video_id: str
    track_number: int
    ethogram_revision_id: str
    ethogram_definition_sha256: str
    start_frame: int
    end_frame: int
    fps: float = Field(gt=0)
    transition_policy: Literal["adjacent-labeled-bouts-only"] = "adjacent-labeled-bouts-only"
    interval_policy: Literal["inclusive-frame-intervals"] = "inclusive-frame-intervals"
    provenance_status: BehaviorProvenanceStatus
    provenance_warning: str | None
    stale_bout_count: int = Field(ge=0)
    channels: list[BehaviorChannelDynamics]
