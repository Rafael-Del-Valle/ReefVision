"""Video extraction and annotation schemas."""

from typing import Any

from pydantic import BaseModel, Field


class VideoExtractJobRequest(BaseModel):
    video_path: str
    frames_path: str
    every_n_frames: int = Field(default=1, ge=1)


class VideoTrackCreateRequest(BaseModel):
    video_id: str
    label_class_id: str
    track_number: int = Field(ge=0)
    geometry_kind: str = "bbox"
    keyframes: list[dict[str, Any]] = Field(default_factory=list)
    interpolation: str = "linear"


class VideoTrackResponse(BaseModel):
    id: str
    video_id: str
    label_class_id: str
    track_number: int
    geometry_kind: str
    keyframes: list[dict[str, Any]]
    interpolation: str
    status: str

    model_config = {"from_attributes": True}
