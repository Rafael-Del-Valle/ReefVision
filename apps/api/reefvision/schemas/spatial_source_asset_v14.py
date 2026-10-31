"""Strict unverified imported 3D original metadata response."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
