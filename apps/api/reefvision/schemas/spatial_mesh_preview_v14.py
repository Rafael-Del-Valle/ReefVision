"""Request contract for bounded, unverified 3D mesh measurements."""

from __future__ import annotations

from math import isclose, isfinite
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    model_validator,
)


class MeshPreviewRequest(BaseModel):
    obj_text: str | None = Field(default=None, max_length=256_000)
    ply_text: str | None = Field(default=None, max_length=256_000)
    glb_base64: str | None = Field(default=None, max_length=350_000)
    vertices: list[list[float]] | None = Field(default=None, max_length=2_000)
    faces: list[list[StrictInt]] | None = Field(default=None, max_length=4_000)
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
    # A caller-provided label for the reconstruction coordinate system, not proof
    # that two surveys are registered or share a verified physical origin.
    coordinate_frame_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )

    surface_path_vertex_pairs: list[list[StrictInt]] | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def geometry_is_unambiguous(self) -> MeshPreviewRequest:
        supplied_text = sum(
            value is not None for value in (self.obj_text, self.ply_text, self.glb_base64)
        )
        if supplied_text:
            if supplied_text != 1 or self.vertices is not None or self.faces is not None:
                raise ValueError("Use OBJ, PLY, GLB, or indexed triangles, not a mixture")
        elif self.vertices is None or self.faces is None:
            raise ValueError("Indexed triangles require vertices and faces")
        if self.surface_path_vertex_pairs is not None:
            for pair in self.surface_path_vertex_pairs:
                if len(pair) != 2 or pair[0] == pair[1] or any(index < 0 for index in pair):
                    raise ValueError("Surface paths require two distinct nonnegative indices")
        return self


class MeshRegistrationEvidence(BaseModel):
    """Caller-supplied pairwise registration diagnostics; never verified."""

    model_config = ConfigDict(extra="forbid")

    source_frame_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    target_frame_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    method: Literal["landmark", "icp", "survey_control", "other"]
    rms_residual_m: StrictFloat = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    correspondence_count: StrictInt = Field(ge=3, le=1_000_000)
    evidence_note: str = Field(min_length=1, max_length=2_000)
    # Optional caller-supplied rigid source-to-target transform in meters.
    # Structural validity does not establish correct alignment or review.
    source_to_target_transform_m: list[list[StrictFloat]] | None = None

    @model_validator(mode="after")
    def validate_rigid_transform(self) -> MeshRegistrationEvidence:
        transform = self.source_to_target_transform_m
        if transform is None:
            return self
        if len(transform) != 4 or any(len(row) != 4 for row in transform):
            raise ValueError("Registration transform must be a 4x4 matrix")
        if any(not isfinite(value) for row in transform for value in row):
            raise ValueError("Registration transform entries must be finite")
        if any(
            not isclose(transform[3][column], expected, rel_tol=0, abs_tol=1e-9)
            for column, expected in enumerate((0.0, 0.0, 0.0, 1.0))
        ):
            raise ValueError("Registration transform must have an affine last row")
        if any(abs(transform[row][3]) > 1_000_000 for row in range(3)):
            raise ValueError("Registration translation must be bounded in meters")
        rotation = [row[:3] for row in transform[:3]]
        for index, row in enumerate(rotation):
            if not isclose(sum(value * value for value in row), 1.0, rel_tol=0, abs_tol=1e-5):
                raise ValueError("Registration transform must have unit rotation axes")
            for other in rotation[index + 1 :]:
                if not isclose(
                    sum(a * b for a, b in zip(row, other, strict=True)),
                    0.0,
                    rel_tol=0,
                    abs_tol=1e-5,
                ):
                    raise ValueError("Registration transform rotation axes must be orthogonal")
        determinant = (
            rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
            - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
            + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
        )
        if not isclose(determinant, 1.0, rel_tol=0, abs_tol=1e-5):
            raise ValueError("Registration transform must be a right-handed rigid rotation")
        return self


class MeshReidentificationEvidence(BaseModel):
    """Provisional source-to-target specimen matching notes, never verified."""

    model_config = ConfigDict(extra="forbid")

    # Optional for legacy evidence; when present, binds the observation pair
    # to a provisional specimen label and prevents cross-specimen reuse.
    specimen_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )

    before_observation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    after_observation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    method: Literal["visual_morphology", "survey_tag", "photo_match", "other"]
    observer_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    evidence_note: str = Field(min_length=1, max_length=2_000)
    # Bind provisional matching evidence to the exact source reconstructions.
    # Both hashes must be supplied together; labels alone are not unique assets.
    before_geometry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    after_geometry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # Optional timepoint binding: observation IDs and geometry hashes alone do
    # not prevent a dated survey record from being silently reassigned.
    before_observed_at_utc: AwareDatetime | None = None
    after_observed_at_utc: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_complete_geometry_binding(self) -> MeshReidentificationEvidence:
        if (self.before_geometry_sha256 is None) != (self.after_geometry_sha256 is None):
            raise ValueError("Reidentification geometry binding requires both SHA-256 fingerprints")
        if (self.before_observed_at_utc is None) != (self.after_observed_at_utc is None):
            raise ValueError("Reidentification timepoint binding requires both UTC timestamps")
        return self


class MeshLongitudinalComparisonRequest(BaseModel):
    before: MeshPreviewRequest
    after: MeshPreviewRequest
    registration_evidence: MeshRegistrationEvidence | None = None
    reidentification_evidence: MeshReidentificationEvidence | None = None
