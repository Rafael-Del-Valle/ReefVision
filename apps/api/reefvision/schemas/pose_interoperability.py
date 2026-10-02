"""External pose interoperability contracts."""

from __future__ import annotations

from typing import Literal

PoseInteroperabilityFormat = Literal[
    "slp",
    "nwb",
    "coco",
    "dlc_csv",
    "ultralytics_pose",
]


from pydantic import BaseModel


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
