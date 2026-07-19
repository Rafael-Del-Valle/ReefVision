"""Rendered video export schemas for tracks and behavior visualization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from reefvision.schemas.jobs import JobResponse


class VideoRenderExportRequest(BaseModel):
    export_kind: Literal["annotated", "trajectory", "heatmap"]
    track_ids: list[str] = Field(default_factory=list, max_length=100_000)
    include_archived_tracks: bool = False
    include_labels: bool = True
    include_confidence: bool = True
    trail_length_frames: int = Field(default=150, ge=1, le=100_000)
    line_thickness: int = Field(default=2, ge=1, le=20)
    heatmap_radius_px: int = Field(default=40, ge=2, le=1000)
    heatmap_opacity: float = Field(default=0.45, ge=0.05, le=0.95)
    output_fps: float | None = Field(default=None, gt=0, le=240)
    maximum_frames: int | None = Field(default=None, ge=1, le=10_000_000)
    codec: Literal["mp4v", "avc1", "MJPG"] = "mp4v"


class VideoRenderExportResponse(BaseModel):
    job: JobResponse
