"""Portable video-track interchange contracts for ReefVision, CSV, and MOT."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer, model_validator

from reefvision.schemas.videos import VideoTrackKeyframe

VideoTrackExchangeFormat = Literal["reefvision_json", "reefvision_csv", "mot_csv"]


class ReefVisionTrackExchangeItem(BaseModel):
    original_track_id: str | None = Field(default=None, max_length=100)
    original_track_number: int | None = Field(default=None, ge=1)
    label_class_id: str | None = Field(default=None, max_length=100)
    label_class_name: str = Field(min_length=1, max_length=200)
    geometry_kind: Literal["bbox"] = "bbox"
    interpolation: Literal["linear", "hold"] = "linear"
    status: str = Field(default="verified", min_length=1, max_length=30)
    keyframes: list[VideoTrackKeyframe] = Field(min_length=1, max_length=100000)
    original_source_model_id: str | None = Field(default=None, max_length=100)
    original_source_job_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("keyframes")
    def serialize_keyframes(self, keyframes: list[VideoTrackKeyframe]) -> list[dict[str, object]]:
        return [item.model_dump(mode="json", exclude_none=True) for item in keyframes]

    @model_validator(mode="after")
    def ordered_unique_frames(self) -> ReefVisionTrackExchangeItem:
        frames = [item.frame for item in self.keyframes]
        if frames != sorted(frames) or len(frames) != len(set(frames)):
            raise ValueError("Exchange track keyframes must use unique ascending frames")
        return self


class ReefVisionVideoTrackExchange(BaseModel):
    schema_version: Literal["reefvision-video-tracks-0001"]
    source_video_id: str | None = None
    source_video_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    source_filename: str | None = None
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    fps: float = Field(gt=0)
    frame_index_base: Literal[0] = 0
    coordinate_base: Literal[0] = 0
    observation_policy: Literal["persisted_keyframes"] = "persisted_keyframes"
    tracks: list[ReefVisionTrackExchangeItem] = Field(default_factory=list, max_length=10000)


class VideoTrackImportResponse(BaseModel):
    schema_version: Literal["video-track-import-0001"]
    video_id: str
    format: VideoTrackExchangeFormat
    created_track_ids: list[str]
    track_count: int
    observation_count: int
    warnings: list[str]
