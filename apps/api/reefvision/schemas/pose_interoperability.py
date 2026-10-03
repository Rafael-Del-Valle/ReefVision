"""External pose interoperability contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PoseInteroperabilityFormat = Literal[
    "slp",
    "nwb",
    "coco",
    "dlc_csv",
    "ultralytics_pose",
]


class PoseInteroperabilityRuntimeResponse(BaseModel):
    available: bool
    required_version: str
    installed_version: str | None
    installation: str
    reason: str | None = None


class PoseInteroperabilityImportResponse(BaseModel):
    schema_version: Literal["pose-interoperability-import-0001"] = (
        "pose-interoperability-import-0001"
    )
    video_id: str
    format: PoseInteroperabilityFormat
    created_track_ids: list[str]
    track_count: int
    keyframe_count: int
    pose_schema_id: str
    pose_schema_revision: int
    used_reefvision_provenance: bool
    warnings: list[str]
