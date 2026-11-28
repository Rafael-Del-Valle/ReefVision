"""Strict unverified imported 3D original metadata response."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SpatialSourceParseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["spatial-source-parse-0001"]
    source_kind_resolved: Literal["mesh", "point_cloud"]
    vertex_count: int | None = Field(default=None, ge=1, strict=True)
    face_count: int | None = Field(default=None, ge=1, strict=True)
    point_count: int | None = Field(default=None, ge=1, strict=True)
    geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qc_warnings: list[str]
    calibration_applied: Literal[False] = False
    calibration_verified: Literal[False] = False
    specimen_identity_verified: Literal[False] = False

    @field_validator(
        "calibration_applied", "calibration_verified", "specimen_identity_verified", mode="before"
    )
    @classmethod
    def validate_unverified_flag(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Structural parse verification flags must be JSON false")
        return value

    @model_validator(mode="after")
    def validate_structural_counts_and_qc(self) -> SpatialSourceParseSummary:
        """Reject internally contradictory or falsely verified parse summaries."""
        if self.source_kind_resolved == "mesh":
            if self.vertex_count is None or self.face_count is None or self.point_count is not None:
                raise ValueError("Mesh parse must have only vertex and face counts")
        elif (
            self.point_count is None or self.vertex_count is not None or self.face_count is not None
        ):
            raise ValueError("Point-cloud parse must have only a point count")
        required_warnings = {
            "physical_calibration_not_applied",
            "structural_parse_unreviewed",
        }
        if not required_warnings.issubset(self.qc_warnings):
            raise ValueError("Structural parse must retain unverified calibration QC")
        return self


class SpatialSourceParseResult(SpatialSourceParseSummary):
    project_id: str
    spatial_source_asset_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_format: Literal["obj", "ply", "glb"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_format_kind(self) -> SpatialSourceParseResult:
        # Stored evidence is emitted with every field, including explicit nulls
        # and false flags. Defaults must not reconstruct an altered digest.
        if not type(self).model_fields.keys() <= self.model_fields_set:
            raise ValueError("Structural parse result must contain all canonical fields")
        if self.source_format in {"obj", "glb"} and self.source_kind_resolved != "mesh":
            raise ValueError("OBJ/GLB structural parses must resolve as meshes")
        return self


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
