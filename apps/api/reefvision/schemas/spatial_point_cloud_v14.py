"""Strict request contract for unverified XYZ point-cloud measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, StrictBool, StrictInt, model_validator


class PointCloudPreviewRequest(BaseModel):
    ply_text: str | None = Field(default=None, max_length=256_000)
    points: list[list[float]] | None = Field(default=None, min_length=1, max_length=2_000)
    meters_per_unit: float = Field(gt=0, le=1_000_000)
    calibration_method: Literal["ruler", "photogrammetry_control", "instrument", "other"]
    calibration_evidence: str = Field(min_length=1, max_length=2_000)
    relative_scale_uncertainty: float | None = Field(default=None, ge=0, le=1)
    source_label: str | None = Field(default=None, max_length=200)
    specimen_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    observation_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    observed_at_utc: AwareDatetime | None = None
    # A caller-supplied source-frame label, never proof of registration.
    coordinate_frame_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    point_index_pairs: list[list[StrictInt]] | None = Field(default=None, max_length=32)
    preserve_axis_extrema_in_preview: StrictBool = False

    @model_validator(mode="after")
    def geometry_is_unambiguous(self) -> PointCloudPreviewRequest:
        if not self.calibration_evidence.strip():
            raise ValueError("Point-cloud calibration evidence cannot be blank")
        if (self.ply_text is None) == (self.points is None):
            raise ValueError("Provide exactly one of vertex-only ASCII PLY or XYZ points")
        return self
