"""Depth-map generation, storage, and depth-aware measurement schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from reefvision.schemas.jobs import JobResponse

DepthKind = Literal["relative", "metric"]
DepthProvider = Literal[
    "luminance_relative",
    "depth_anything_v2_relative",
    "depth_anything_v2_metric",
    "imported",
]


class CameraIntrinsics(BaseModel):
    fx_px: FiniteFloat = Field(gt=0)
    fy_px: FiniteFloat = Field(gt=0)
    cx_px: FiniteFloat
    cy_px: FiniteFloat


class DepthMapGenerateRequest(BaseModel):
    provider_id: DepthProvider = "depth_anything_v2_relative"
    model_id: str = Field(
        default="depth-anything/Depth-Anything-V2-Small-hf",
        min_length=1,
        max_length=500,
    )
    model_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    device: str = Field(default="auto", min_length=1, max_length=60)
    local_files_only: bool = True
    depth_kind: DepthKind = "relative"
    unit: str | None = Field(default=None, max_length=30)
    maximum_metric_depth: FiniteFloat | None = Field(default=None, gt=0)
    camera_intrinsics: CameraIntrinsics | None = None

    @model_validator(mode="after")
    def validate_provider_kind(self) -> DepthMapGenerateRequest:
        if self.provider_id == "depth_anything_v2_metric" and self.depth_kind != "metric":
            raise ValueError("The metric provider requires depth_kind='metric'")
        if self.provider_id in {
            "luminance_relative",
            "depth_anything_v2_relative",
        } and self.depth_kind != "relative":
            raise ValueError("The selected provider produces relative depth only")
        if self.depth_kind == "metric" and not self.unit:
            self.unit = "m"
        if self.depth_kind == "relative":
            self.unit = None
        return self


class DepthMapImportRequest(BaseModel):
    values: list[list[FiniteFloat]] = Field(min_length=1, max_length=16_384)
    depth_kind: DepthKind
    unit: str | None = Field(default=None, max_length=30)
    provider_id: str = Field(default="imported", min_length=1, max_length=120)
    model_id: str = Field(default="external-depth-map", min_length=1, max_length=500)
    model_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    camera_intrinsics: CameraIntrinsics | None = None

    @model_validator(mode="after")
    def rectangular_values(self) -> DepthMapImportRequest:
        width = len(self.values[0])
        if width <= 0:
            raise ValueError("Depth maps cannot contain empty rows")
        if any(len(row) != width for row in self.values):
            raise ValueError("Depth map rows must have equal length")
        if width > 16_384:
            raise ValueError("Depth map width exceeds 16384 pixels")
        if self.depth_kind == "metric" and not self.unit:
            self.unit = "m"
        if self.depth_kind == "relative":
            self.unit = None
        return self


class DepthMapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    image_id: str
    provider_id: str
    model_id: str
    model_checksum: str | None
    depth_kind: str
    unit: str | None
    managed_path: str
    preview_path: str
    sha256: str
    width_px: int
    height_px: int
    minimum_depth: float
    maximum_depth: float
    median_depth: float
    valid_pixel_count: int
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DepthMapJobResponse(BaseModel):
    depth_map_id: str
    job: JobResponse


class DepthValueSummary(BaseModel):
    valid_pixel_count: int
    minimum: float | None
    percentile_05: float | None
    median: float | None
    mean: float | None
    percentile_95: float | None
    maximum: float | None


class DepthAwareMaskMeasurementResponse(BaseModel):
    mask_annotation_id: str
    image_id: str
    depth_map_id: str
    depth_kind: DepthKind
    unit: str | None
    depth: DepthValueSummary
    pixel_area: int
    depth_weighted_area_index: float | None
    metric_area: float | None
    metric_width: float | None
    metric_height: float | None
    centroid_x: float | None
    centroid_y: float | None
    centroid_z: float | None
    camera_intrinsics: CameraIntrinsics | None
    method: str
    warnings: list[str]


class DepthTrackSample(BaseModel):
    track_id: str = Field(min_length=1, max_length=100)
    frame_index: int = Field(ge=0)
    center_x_px: FiniteFloat
    center_y_px: FiniteFloat
    depth: FiniteFloat = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class DepthTrackAnalyticsRequest(BaseModel):
    fps: FiniteFloat = Field(gt=0)
    camera_intrinsics: CameraIntrinsics
    unit: str = Field(default="m", min_length=1, max_length=30)
    samples: list[DepthTrackSample] = Field(min_length=2, max_length=2_000_000)
    maximum_frame_gap: int | None = Field(default=None, ge=1, le=100_000)


class DepthTrackPoint3D(BaseModel):
    frame_index: int
    x: float
    y: float
    z: float


class DepthTrack3DAnalytics(BaseModel):
    track_id: str
    observed_frame_count: int
    first_frame: int
    last_frame: int
    duration_seconds: float
    distance_3d: float
    net_displacement_3d: float
    mean_speed_3d_per_second: float
    maximum_speed_3d_per_second: float
    mean_depth: float
    minimum_depth: float
    maximum_depth: float
    points: list[DepthTrackPoint3D]
    skipped_gap_count: int


class DepthTrackAnalyticsResponse(BaseModel):
    fps: float
    unit: str
    tracks: list[DepthTrack3DAnalytics]
    warnings: list[str]


class DepthTrainingConfiguration(BaseModel):
    input_mode: Literal[
        "none",
        "fourth_channel",
        "early_fusion",
        "late_fusion",
        "auxiliary_depth_loss",
    ] = "none"
    depth_provider_id: str | None = Field(default=None, max_length=120)
    require_metric_depth: bool = False
    missing_depth_policy: Literal["block", "zeros", "median", "exclude"] = "block"
    normalize: Literal["per_image", "dataset", "metric", "none"] = "per_image"
