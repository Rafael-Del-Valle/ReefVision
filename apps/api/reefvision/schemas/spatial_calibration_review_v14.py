"""Typed API contracts for durable, provisional 3D calibration QC receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence


class SpatialCalibrationReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: MeshCalibrationReviewEvidence


class SpatialCalibrationReviewResponse(BaseModel):
    id: str
    project_id: str
    spatial_source_asset_id: str
    source_sha256: str
    evidence_sha256: str
    evidence: MeshCalibrationReviewEvidence
    created_at: datetime
    review_status: Literal["attributed_unverified"] = "attributed_unverified"
    calibration_verified: bool = False
    specimen_identity_verified: bool = False
    reviewer_authenticated: bool = False
    source_integrity_checked: bool = True
