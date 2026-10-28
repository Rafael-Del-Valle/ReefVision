"""Strict request contract for unverified XYZ point-cloud measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence

class PointCloudPreviewRequest(BaseModel):
    ply_text: str | None = Field(default=None, max_length=256_000)
    points: list[list[float]] | None = Field(default=None, min_length=1, max_length=2_000)
    meters_per_unit: float = Field(gt=0, le=1_000_000)
    calibration_method: Literal["ruler", "photogrammetry_control", "instrument", "other"]
    calibration_evidence: str = Field(min_length=1, max_length=2_000)
    relative_scale_uncertainty: float | None = Field(default=None, ge=0, le=1)
    calibration_review: MeshCalibrationReviewEvidence | None = None
    source_label: str | None = Field(default=None, max_length=200)
    # Optional byte-exact replay guard for the submitted ASCII PLY text.
    # A matching digest does not verify calibration or specimen identity.
    expected_source_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
    preserve_measured_chord_endpoints_in_preview: StrictBool = False

    @field_validator("meters_per_unit", "relative_scale_uncertainty", mode="before")
    @classmethod
    def calibration_numbers_are_not_coerced(cls, value: object) -> object:
        # Pydantic otherwise converts True to 1.0 and numeric strings to floats.
        if value is not None and type(value) not in (int, float):
            raise ValueError("Calibration values must be JSON numbers, not booleans or strings")
        return value

    @field_validator("points", mode="before")
    @classmethod
    def xyz_numbers_are_not_coerced(cls, value: object) -> object:
        if isinstance(value, list):
            for point in value:
                if isinstance(point, list) and any(
                    type(coordinate) not in (int, float) for coordinate in point
                ):
                    raise ValueError("XYZ coordinates must be JSON numbers")
        return value

    @model_validator(mode="after")
    def geometry_is_unambiguous(self) -> PointCloudPreviewRequest:
        if not self.calibration_evidence.strip():
            raise ValueError("Point-cloud calibration evidence cannot be blank")
        if (self.ply_text is None) == (self.points is None):
            raise ValueError("Provide exactly one of vertex-only ASCII PLY or XYZ points")
        if self.expected_source_payload_sha256 is not None and self.ply_text is None:
            raise ValueError("Source SHA-256 binding requires an imported ASCII PLY point cloud")
        return self
