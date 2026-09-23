"""Typed readiness diagnostics for production video georeferencing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat

VideoGeoreferencingReadinessState = Literal[
    "ready",
    "missing_calibration",
    "invalid_calibration",
    "missing_surface_reference",
    "missing_telemetry",
    "alignment_problem",
    "synchronization_problem",
    "zoom_mismatch",
]

VideoGeoreferencingReadinessIssueCode = Literal[
    "missing_calibration",
    "invalid_calibration",
    "missing_surface_reference",
    "missing_telemetry",
    "invalid_airdata_alignment",
    "telemetry_out_of_sync",
    "calibration_zoom_mismatch",
]


class VideoGeoreferencingReadinessIssue(BaseModel):
    code: VideoGeoreferencingReadinessIssueCode
    message: str


class VideoGeoreferencingReadinessResponse(BaseModel):
    schema_version: Literal["video-georeferencing-readiness-0001"]
    video_id: str
    project_id: str
    ready: bool
    state: VideoGeoreferencingReadinessState
    issues: list[VideoGeoreferencingReadinessIssue]
    srt_available: bool
    airdata_available: bool
    airdata_alignment_valid: bool
    surface_reference_configured: bool
    calibration_available: bool
    calibration_valid: bool
    calibration_checksum_sha256: str | None = None
    sampled_frame_indices: list[int]
    synchronized_frame_count: int = Field(ge=0)
    sampled_frame_count: int = Field(ge=0)
    maximum_sync_error_s: FiniteFloat | None = Field(default=None, ge=0)
    zoom_compatible: bool | None = None
    max_allowed_sync_error_s: FiniteFloat = Field(gt=0)
