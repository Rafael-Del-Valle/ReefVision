"""Revision-safe video-track correction operation schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, FiniteFloat, model_validator

from reefvision.schemas.videos import VideoTrackResponse


class TrackKeyframeWrite(BaseModel):
    frame_index: int = Field(ge=0)
    x: FiniteFloat
    y: FiniteFloat
    width: FiniteFloat = Field(gt=0)
    height: FiniteFloat = Field(gt=0)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    occluded: bool = False
    identity_uncertain: bool = False


class TrackSplitRequest(BaseModel):
    split_frame: int = Field(ge=1)
    new_track_key: str | None = Field(default=None, max_length=200)
    expected_revision: int = Field(ge=1)


class TrackMergeRequest(BaseModel):
    primary_track_id: str
    secondary_track_id: str
    expected_primary_revision: int = Field(ge=1)
    expected_secondary_revision: int = Field(ge=1)
    conflict_policy: str = Field(default="highest_confidence", pattern="^(highest_confidence|primary)$")

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

    @model_validator(mode="after")
    def distinct_tracks(self) -> TrackIdentitySwapRequest:
        if self.first_track_id == self.second_track_id:
            raise ValueError("Identity-swap tracks must be distinct")
        return self


class TrackOperationResponse(BaseModel):
    operation: str
    tracks: list[VideoTrackResponse]
    deleted_track_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
