"""Typed production-service results for video georeferencing."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, FiniteFloat, model_validator

from reefvision.geospatial.models import TelemetryProvenance
from reefvision.geospatial.projection import GeoreferenceResult

VideoGeoreferenceFailureReason = Literal[
    "frame_out_of_range",
    "telemetry_unavailable",
    "telemetry_out_of_sync",
    "calibration_unavailable",
    "calibration_mismatch",
    "calibration_zoom_mismatch",
    "surface_reference_unavailable",
    "projection_failed",
]


class VideoGeoreferenceResponse(BaseModel):
    """One production georeferencing attempt with explicit success/failure state."""

    model_config = {"frozen": True}

    status: Literal["success", "failed"]
    video_id: str
    project_id: str
    frame_index: int = Field(ge=0)
    timestamp_seconds: FiniteFloat = Field(ge=0)
    pixel_x: FiniteFloat
    pixel_y: FiniteFloat
    sync_error_s: FiniteFloat | None = Field(default=None, ge=0)
    telemetry_delta_s: FiniteFloat | None = None
    telemetry_provenance: TelemetryProvenance | None = None
    result: GeoreferenceResult | None = None
    failure_reason: VideoGeoreferenceFailureReason | None = None
    message: str | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if self.status == "success":
            if self.result is None or self.failure_reason is not None or self.message is not None:
                raise ValueError("Successful georeferencing requires a result and no failure")
        elif (
            self.result is not None
            or self.failure_reason is None
            or not (self.message or "").strip()
        ):
            raise ValueError("Failed georeferencing requires a reason/message and no result")
        return self
