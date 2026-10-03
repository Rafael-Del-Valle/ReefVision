"""Scientist-facing pose visualization analytics schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

PoseVisualizationIdentityStatus = Literal["not_built", "current", "stale"]
PoseVisualizationCoordinateKind = Literal["observed", "predicted"]
PoseVisualizationExportFormat = Literal["json", "cells_csv", "trajectories_csv"]


class PoseVisualizationRequest(BaseModel):
    grid_rows: int = Field(default=24, ge=1, le=100)
    grid_columns: int = Field(default=24, ge=1, le=100)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    include_predicted: bool = False
    include_uncertain: bool = True
    minimum_landmark_confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self) -> PoseVisualizationRequest:
        if (
            self.start_frame is not None
            and self.end_frame is not None
            and self.end_frame < self.start_frame
        ):
            raise ValueError("end_frame must be greater than or equal to start_frame")
        return self


class PoseVisualizationPoint(BaseModel):
    frame_index: int = Field(ge=0)
    time_s: float
    semantic_label: str
    occurrence_index: int = Field(ge=0)
    x_px: float
    y_px: float
    landmark_confidence: float | None = Field(default=None, ge=0, le=1)
    visibility_state: str
    observation_source: str
    coordinate_kind: PoseVisualizationCoordinateKind
    landmark_track_id: str | None = None
    association_state: str | None = None
    verification_state: str | None = None


class PoseVisualizationTrajectorySegment(BaseModel):
    segment_index: int = Field(ge=0)
    points: list[PoseVisualizationPoint]
    path_length_pixels: float = Field(ge=0)
    evaluated_seconds: float = Field(ge=0)
    movement_segment_count: int = Field(ge=0)


class PoseVisualizationTrajectory(BaseModel):
    landmark_track_id: str
    semantic_label: str
    lifecycle_state: str
    points: list[PoseVisualizationPoint]
    segments: list[PoseVisualizationTrajectorySegment]
    path_length_pixels: float = Field(ge=0)
    evaluated_seconds: float = Field(ge=0)
    movement_segment_count: int = Field(ge=0)


class PoseVisualizationCell(BaseModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    x_min_pixels: float
    y_min_pixels: float
    x_max_pixels: float
    y_max_pixels: float
    sample_count: int = Field(ge=0)
    observed_sample_count: int = Field(ge=0)
    predicted_sample_count: int = Field(ge=0)
    confidence_sample_count: int = Field(ge=0)
    mean_landmark_confidence: float | None = Field(default=None, ge=0, le=1)
    sample_fraction: float = Field(ge=0, le=1)
    occupied_sampled_frame_count: int = Field(ge=0)
    occupied_sampled_frame_fraction: float = Field(ge=0, le=1)
    unique_landmark_track_count: int = Field(ge=0)
    movement_segment_count: int = Field(ge=0)
    movement_distance_pixels: float = Field(ge=0)
    movement_duration_seconds: float = Field(ge=0)
    mean_speed_pixels_per_second: float | None = Field(default=None, ge=0)
    maximum_speed_pixels_per_second: float | None = Field(default=None, ge=0)


class PoseProviderVisualizationCapabilities(BaseModel):
    provider_name: str | None
    keypoint_scores_persisted: bool
    native_confidence_maps_persisted: bool
    part_affinity_fields_persisted: bool
    raw_tensor_export_available: bool
    reason: str


class PosePafAvailability(BaseModel):
    available: bool
    provider_name: str | None
    representation: Literal["part_affinity_fields"] = "part_affinity_fields"
    persistence_state: Literal["persisted", "not_persisted"] = "not_persisted"
    reason: str


class PoseVisualizationResponse(BaseModel):
    schema_version: Literal["pose-visualization-0001"] = "pose-visualization-0001"
    parent_video_track_id: str
    source_track_revision: int
    video_id: str
    coordinate_space: Literal["source_pixels"] = "source_pixels"
    video_width_pixels: int = Field(gt=0)
    video_height_pixels: int = Field(gt=0)
    fps: float = Field(gt=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    grid_rows: int = Field(ge=1)
    grid_columns: int = Field(ge=1)
    sampling_policy: Literal["persisted_canonical_pose_keyframes"] = (
        "persisted_canonical_pose_keyframes"
    )
    predicted_coordinate_policy: Literal[
        "exclude_occluded_predictions",
        "include_occluded_predictions",
    ]
    identity_policy: Literal["latest_resolved_temporal_association"] = (
        "latest_resolved_temporal_association"
    )
    identity_status: PoseVisualizationIdentityStatus
    identity_warning: str | None
    sampled_frame_count: int = Field(ge=0)
    spatial_sample_count: int = Field(ge=0)
    observed_sample_count: int = Field(ge=0)
    predicted_sample_count: int = Field(ge=0)
    resolved_identity_sample_count: int = Field(ge=0)
    unresolved_identity_sample_count: int = Field(ge=0)
    excluded_missing_coordinate_count: int = Field(ge=0)
    excluded_filter_count: int = Field(ge=0)
    activity_segment_count: int = Field(ge=0)
    cells: list[PoseVisualizationCell]
    trajectories: list[PoseVisualizationTrajectory]
    provider_capabilities: PoseProviderVisualizationCapabilities
    paf: PosePafAvailability
