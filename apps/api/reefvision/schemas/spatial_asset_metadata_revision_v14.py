"""Typed immutable metadata revision contracts for project-owned 3D originals."""

from __future__ import annotations

from datetime import datetime
from math import isclose, isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CoordinateUnit = Literal["meter", "millimeter", "centimeter", "micrometer", "unitless", "unknown"]
ReviewState = Literal["unreviewed", "attributed_unverified", "rejected"]

_METERS_BY_UNIT = {
    "meter": 1.0,
    "millimeter": 0.001,
    "centimeter": 0.01,
    "micrometer": 0.000001,
}


class SpatialAssetMetadataRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coordinate_unit: CoordinateUnit
    meters_per_unit: float | None = Field(default=None, gt=0, le=1_000_000)
    coordinate_frame_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    transform_to_project_frame: list[list[float]] | None = None
    calibration_evidence: str | None = Field(default=None, min_length=1, max_length=2_000)
    review_state: ReviewState = "unreviewed"
    reviewed_by_identity: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    review_note: str | None = Field(default=None, min_length=1, max_length=2_000)
    created_by_identity: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )

    @model_validator(mode="after")
    def validate_scientific_metadata(self) -> SpatialAssetMetadataRevisionCreate:
        expected_scale = _METERS_BY_UNIT.get(self.coordinate_unit)
        if expected_scale is not None and (
            self.meters_per_unit is None
            or not isclose(self.meters_per_unit, expected_scale, rel_tol=0, abs_tol=1e-15)
        ):
            raise ValueError(
                "Physical coordinate unit requires its canonical meters-per-unit scale"
            )
        if self.coordinate_unit in {"unitless", "unknown"} and self.meters_per_unit is not None:
            raise ValueError("Unitless or unknown coordinates cannot declare a physical scale")
        if self.meters_per_unit is not None and not (self.calibration_evidence or "").strip():
            raise ValueError("Physical scale requires calibration evidence")
        if self.transform_to_project_frame is not None:
            matrix = self.transform_to_project_frame
            if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
                raise ValueError("Transform to project frame must be a 4 by 4 matrix")
            if any(not isfinite(value) for row in matrix for value in row):
                raise ValueError("Transform to project frame must contain finite values")
            if matrix[3] != [0.0, 0.0, 0.0, 1.0]:
                raise ValueError("Transform to project frame must be an affine homogeneous matrix")
            if self.coordinate_frame_id is None:
                raise ValueError("Transform requires a declared source coordinate frame")
        attributed = self.review_state in {"attributed_unverified", "rejected"}
        if attributed and (
            self.reviewed_by_identity is None or not (self.review_note or "").strip()
        ):
            raise ValueError("Attributed review state requires reviewer identity and note")
        if not attributed and (
            self.reviewed_by_identity is not None or self.review_note is not None
        ):
            raise ValueError("Unreviewed metadata cannot carry reviewer attribution")
        return self


class SpatialAssetMetadataRevisionResponse(SpatialAssetMetadataRevisionCreate):
    id: str
    project_id: str
    spatial_source_asset_id: str
    previous_revision_id: str | None
    revision: int
    source_sha256: str
    content_sha256: str
    created_at: datetime
    reviewer_authenticated: bool = False
    calibration_verified: bool = False
    transform_verified: bool = False
