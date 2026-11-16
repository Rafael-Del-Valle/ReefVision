"""Strict unverified imported 3D original metadata response."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SpatialSourceParseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["spatial-source-parse-0001"]
    source_kind_resolved: Literal["mesh", "point_cloud"]
    vertex_count: int | None = Field(default=None, ge=1)
    face_count: int | None = Field(default=None, ge=1)
    point_count: int | None = Field(default=None, ge=1)
    geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qc_warnings: list[str]
    calibration_applied: Literal[False] = False
    calibration_verified: Literal[False] = False
    specimen_identity_verified: Literal[False] = False


class SpatialSourceParseResult(SpatialSourceParseSummary):
    project_id: str
    spatial_source_asset_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_format: Literal["obj", "ply", "glb"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SpatialSourceAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    original_filename: str
    source_format: Literal["obj", "ply", "glb"]
    source_kind: Literal["mesh", "mesh_or_point_cloud"]
    sha256: str
    size_bytes: int
    created_at: datetime
    measurement_status: Literal["source_unreviewed"] = "source_unreviewed"
    calibration_verified: bool = False
    specimen_identity_verified: bool = False
    parse_job_id: str | None = None
    parse_status: Literal[
        "not_queued",
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancel_requested",
        "cancelled",
    ] = "not_queued"
    parse_summary: SpatialSourceParseSummary | None = None
