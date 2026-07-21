"""Rendered video export schemas for tracks and behavior visualization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


VideoDataExportFormat = Literal["csv", "json", "mot", "npz"]


def _default_data_export_formats() -> list[VideoDataExportFormat]:
    return ["csv", "json", "mot"]


class VideoDataExportRequest(BaseModel):
    formats: list[VideoDataExportFormat] = Field(
        default_factory=_default_data_export_formats,
        min_length=1,
        max_length=4,
    )
    include_interpolated: bool = True
    include_archived_tracks: bool = False
    include_analysis_runs: bool = True
    include_evaluation_runs: bool = True

    @model_validator(mode="after")
    def unique_formats(self) -> VideoDataExportRequest:
        if len(self.formats) != len(set(self.formats)):
            raise ValueError("Video data export formats must be unique")
        return self


class VideoDataExportResponse(BaseModel):
    artifact_id: str
    video_id: str
    archive_path: str
    manifest_path: str
    archive_sha256: str
    archive_size_bytes: int = Field(ge=0)
    manifest_sha256: str
    formats: list[str]
