"""Typed read-only connected branch edit proposals, not accepted measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    physical_length_computed: Literal[False] = False
    geometry_space: Literal["source_image_pixels_2d"] = "source_image_pixels_2d"
