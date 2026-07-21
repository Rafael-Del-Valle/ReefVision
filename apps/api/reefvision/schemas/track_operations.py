"""Revision-safe video-track correction operation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, FiniteFloat, model_validator

from reefvision.schemas.videos import VideoTrackKeyframe, VideoTrackResponse


class TrackOperationRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    actor: str = Field(default="local_user", min_length=1, max_length=100)


class TrackKeyframeWrite(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=36)
    frame_index: int = Field(ge=0)
    timestamp_seconds: FiniteFloat | None = Field(default=None, ge=0)
    x: FiniteFloat
    y: FiniteFloat
    width: FiniteFloat = Field(gt=0)
    height: FiniteFloat = Field(gt=0)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    occluded: bool = False
    identity_uncertain: bool = False


class TrackObservationAddRequest(TrackOperationRequest):
    observation: VideoTrackKeyframe


class TrackObservationUpdateRequest(TrackOperationRequest):
    frame_index: int | None = Field(default=None, ge=0)
    timestamp_seconds: FiniteFloat | None = Field(default=None, ge=0)
    x_min: FiniteFloat | None = Field(default=None, ge=0)
    y_min: FiniteFloat | None = Field(default=None, ge=0)
    x_max: FiniteFloat | None = Field(default=None, gt=0)
    y_max: FiniteFloat | None = Field(default=None, gt=0)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)


class TrackObservationDeleteRequest(TrackOperationRequest):
    pass


class TrackObservationRestoreRequest(TrackOperationRequest):
    pass


class TrackSplitRequest(BaseModel):
    split_frame: int = Field(ge=1)
    new_track_key: str | None = Field(default=None, max_length=200)
    expected_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=100)
    actor: str = Field(default="local_user", min_length=1, max_length=100)


class TrackMergeRequest(BaseModel):
    primary_track_id: str
    secondary_track_id: str
    expected_primary_revision: int = Field(ge=1)
    expected_secondary_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=100)
    actor: str = Field(default="local_user", min_length=1, max_length=100)
    conflict_policy: str = Field(
        default="highest_confidence", pattern="^(highest_confidence|primary)$"
    )

    @model_validator(mode="after")
    def distinct_tracks(self) -> TrackMergeRequest:
        if self.primary_track_id == self.secondary_track_id:
            raise ValueError("Merge tracks must be distinct")
        return self


class TrackIdentitySwapRequest(BaseModel):
    first_track_id: str
    second_track_id: str
    after_frame: int = Field(ge=0)
    expected_first_revision: int = Field(ge=1)
    expected_second_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=100)
    actor: str = Field(default="local_user", min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_tracks(self) -> TrackIdentitySwapRequest:
        if self.first_track_id == self.second_track_id:
            raise ValueError("Identity-swap tracks must be distinct")
        return self


class TrackObservationReassignRequest(BaseModel):
    source_track_id: str = Field(min_length=1, max_length=36)
    target_track_id: str = Field(min_length=1, max_length=36)
    observation_ids: list[str] = Field(min_length=1)
    expected_source_revision: int = Field(ge=1)
    expected_target_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=100)
    actor: str = Field(default="local_user", min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_tracks_and_observations(self) -> TrackObservationReassignRequest:
        if self.source_track_id == self.target_track_id:
            raise ValueError("Observation reassignment requires distinct tracks")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("Observation IDs must be unique")
        return self


class TrackDeleteRequest(TrackOperationRequest):
    pass


class TrackRestoreRequest(TrackOperationRequest):
    pass


class TrackOperationResponse(BaseModel):
    operation: str
    operation_id: str | None = None
    tracks: list[VideoTrackResponse]
    deleted_track_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    replayed: bool = False


class VideoTrackEventResponse(BaseModel):
    id: str
    video_track_id: str
    video_id: str
    operation_id: str | None
    event_type: str
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    result_json: dict[str, Any]
    actor: str
    created_at: datetime
