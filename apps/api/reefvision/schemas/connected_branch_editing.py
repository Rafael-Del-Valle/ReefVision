"""Typed read-only connected branch edit proposals, not accepted measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reefvision.schemas.skeletonization import SkeletonPixelEdit


class ConnectedBranchPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_id: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    points: list[SkeletonPixelEdit] = Field(min_length=2)


class ConnectedBranchNodeResponse(BaseModel):
    id: str
    kind: Literal["endpoint", "junction", "isolated", "cycle_anchor"]
    x: float
    y: float
    source_pixels: list[SkeletonPixelEdit]
    external_connection_count: int = Field(ge=0)


class ConnectedBranchEdgeResponse(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    pixels: list[SkeletonPixelEdit]
    boundary_to_boundary_length_pixels: float = Field(ge=0)
    node_to_node_length_pixels: float = Field(ge=0)
    is_cycle: bool
    length_physical: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ConnectedBranchCalibrationResponse(BaseModel):
    calibration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method: Literal["scalar_distance_per_pixel", "reference_plane_homography"]
    unit: str = Field(min_length=1, max_length=32)
    source: str = Field(min_length=1, max_length=100)
    original_total_length: float = Field(ge=0, allow_inf_nan=False)
    proposed_total_length: float = Field(ge=0, allow_inf_nan=False)
    added_length: float = Field(gt=0, allow_inf_nan=False)


class ConnectedBranchPreviewResponse(BaseModel):
    schema_version: Literal["connected-branch-preview-0001"] = "connected-branch-preview-0001"
    base_analysis_id: str
    base_result_sha256: str
    image_id: str
    mask_annotation_id: str
    attached_node_id: str | None
    added_edge_id: str
    superseded_edge_ids: list[str]
    replacement_edge_ids: list[str]
    original_total_length_pixels: float = Field(ge=0)
    proposed_total_length_pixels: float = Field(ge=0)
    added_length_pixels: float = Field(gt=0)
    nodes: list[ConnectedBranchNodeResponse]
    edges: list[ConnectedBranchEdgeResponse]
    evidence_level: Literal["proposal_unverified"] = "proposal_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"
    persistent_change_applied: Literal[False] = False
    physical_length_computed: bool = False
    calibration: ConnectedBranchCalibrationResponse | None = None
    geometry_space: Literal["source_image_pixels_2d"] = "source_image_pixels_2d"

    @model_validator(mode="after")
    def validate_physical_lengths(self) -> ConnectedBranchPreviewResponse:
        calibrated = self.calibration is not None
        if self.physical_length_computed != calibrated or any(
            (edge.length_physical is not None) != calibrated for edge in self.edges
        ):
            raise ValueError("Branch preview physical lengths must match its calibration status")
        return self
