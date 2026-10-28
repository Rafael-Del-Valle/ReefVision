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


class MeshCalibrationReviewEvidence(BaseModel):
    """Independently attributed calibration QC; never certifies physical scale."""

    model_config = ConfigDict(extra="forbid")

    calibration_operator_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    independent_reviewer_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    independent_review_decision: Literal["supports_scale", "disputes_scale", "inconclusive"]
    independent_review_note: str = Field(min_length=1, max_length=2_000)
    reviewed_at_utc: AwareDatetime
    # Bind the review to geometry and every scale-bearing calibration input.
    reviewed_geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Optional byte-exact binding for imported OBJ, PLY, or GLB source files.
    reviewed_source_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # Optional review binding to the caller-supplied source frame label.
    # Matching frame labels never establish coordinate registration.
    reviewed_coordinate_frame_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    reviewed_specimen_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    reviewed_observation_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    reviewed_observed_at_utc: AwareDatetime | None = None
    reviewed_meters_per_unit: StrictFloat = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    reviewed_calibration_method: Literal["ruler", "photogrammetry_control", "instrument", "other"]
    reviewed_calibration_evidence: str = Field(min_length=1, max_length=2_000)
    reviewed_relative_scale_uncertainty: StrictFloat | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def independent_review_is_attributed(self) -> MeshCalibrationReviewEvidence:
        if self.calibration_operator_id.casefold() == self.independent_reviewer_id.casefold():
            raise ValueError("Independent calibration reviewer must differ from operator")
        if not self.independent_review_note.strip():
            raise ValueError("Independent calibration review note cannot be blank")
        if not self.reviewed_calibration_evidence.strip():
            raise ValueError("Reviewed calibration evidence cannot be blank")
        return self


class MeshPreviewRequest(BaseModel):
    obj_text: str | None = Field(default=None, max_length=256_000)
    ply_text: str | None = Field(default=None, max_length=256_000)
    glb_base64: str | None = Field(default=None, max_length=350_000)
    vertices: list[list[StrictFloat | StrictInt]] | None = Field(default=None, max_length=2_000)
    faces: list[list[StrictInt]] | None = Field(default=None, max_length=4_000)
    meters_per_unit: StrictFloat | StrictInt = Field(gt=0, le=1_000_000)
    calibration_method: Literal["ruler", "photogrammetry_control", "instrument", "other"]
    calibration_evidence: str = Field(min_length=1, max_length=2_000)
    relative_scale_uncertainty: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=1)
    calibration_review: MeshCalibrationReviewEvidence | None = None
    source_label: str | None = Field(default=None, max_length=200)
    # Optional replay guard for imported source bytes (OBJ/PLY UTF-8 or decoded GLB).
    # Matching bytes do not establish calibration, specimen identity or human review.
    expected_source_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
        if not self.calibration_evidence.strip():
            raise ValueError("Mesh calibration evidence cannot be blank")
        supplied_text = sum(
            value is not None for value in (self.obj_text, self.ply_text, self.glb_base64)
        )
        if supplied_text:
            if supplied_text != 1 or self.vertices is not None or self.faces is not None:
                raise ValueError("Use OBJ, PLY, GLB, or indexed triangles, not a mixture")
        elif self.vertices is None or self.faces is None:
            raise ValueError("Indexed triangles require vertices and faces")
        if self.expected_source_payload_sha256 is not None and not supplied_text:
            raise ValueError("Source SHA-256 binding requires an imported OBJ, PLY, or GLB file")
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
    # Optional separately attributed registration review is audit evidence,
    # not proof of accurate spatial alignment or scientific verification.
    registration_operator_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    independent_reviewer_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    independent_review_decision: (
        Literal["supports_alignment", "disputes_alignment", "inconclusive"] | None
    ) = None
    independent_review_note: str | None = Field(default=None, min_length=1, max_length=2_000)
    independent_reviewed_at_utc: AwareDatetime | None = None
    # Optional project, observation and timepoint bindings prevent evidence
    # reuse across surveys with recycled local frame labels or geometry.
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_observation_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    target_observation_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    source_observed_at_utc: AwareDatetime | None = None
    target_observed_at_utc: AwareDatetime | None = None
    # Optional paired source fingerprints prevent stale registration reuse.
    # This is a consistency binding, not proof of alignment or identity.
    source_geometry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target_geometry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # The same reconstruction may be recalibrated without changing its geometry
    # hash. Pairwise scale bindings prevent reusing a meter-valued transform
    # against a newly scaled mesh; these remain unverified caller evidence.
    source_meters_per_mesh_unit: StrictFloat | None = Field(
        default=None, gt=0, le=1_000_000, allow_inf_nan=False
    )
    target_meters_per_mesh_unit: StrictFloat | None = Field(
        default=None, gt=0, le=1_000_000, allow_inf_nan=False
    )
    # A revised calibration uncertainty changes the interpretation of
    # longitudinal intervals without changing the mesh or its central scale.
    # These optional paired values bind the registration to that QC revision.
    source_relative_scale_uncertainty: StrictFloat | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    target_relative_scale_uncertainty: StrictFloat | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    # Method and supporting evidence can be revised while geometry, scale,
    # and uncertainty remain identical. Bind both source calibration records
    # to prevent silently reusing registration after that provenance revision.
    source_calibration_method: (
        Literal["ruler", "photogrammetry_control", "instrument", "other"] | None
    ) = None
    target_calibration_method: (
        Literal["ruler", "photogrammetry_control", "instrument", "other"] | None
    ) = None
    source_calibration_evidence: str | None = Field(default=None, min_length=1, max_length=2_000)
    target_calibration_evidence: str | None = Field(default=None, min_length=1, max_length=2_000)
    # Optional caller-supplied rigid source-to-target transform in meters.
    # Structural validity does not establish correct alignment or review.
    source_to_target_transform_m: list[list[StrictFloat]] | None = None
    # Optional *absolute Euclidean error bounds*, in meters, supplied by the
    # researcher. They are not inferred from registration RMS or calibration.
    # All three are required to bound target-frame centroid separation.
    source_centroid_position_error_bound_m: StrictFloat | None = Field(
        default=None, ge=0, le=1_000_000, allow_inf_nan=False
    )
    target_centroid_position_error_bound_m: StrictFloat | None = Field(
        default=None, ge=0, le=1_000_000, allow_inf_nan=False
    )
    registration_alignment_error_bound_m: StrictFloat | None = Field(
        default=None, ge=0, le=1_000_000, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def validate_rigid_transform(self) -> MeshRegistrationEvidence:
        if (self.source_observation_id is None) != (self.target_observation_id is None):
            raise ValueError("Registration observation binding requires both observation IDs")
        if (self.source_observed_at_utc is None) != (self.target_observed_at_utc is None):
            raise ValueError("Registration timepoint binding requires both UTC timestamps")
        if (self.source_geometry_sha256 is None) != (self.target_geometry_sha256 is None):
            raise ValueError("Registration geometry binding requires both SHA-256 fingerprints")
        if (self.source_meters_per_mesh_unit is None) != (self.target_meters_per_mesh_unit is None):
            raise ValueError("Registration calibration scale binding requires both scales")
        if (self.source_relative_scale_uncertainty is None) != (
            self.target_relative_scale_uncertainty is None
        ):
            raise ValueError("Registration scale uncertainty binding requires both values")
        calibration_records = (
            self.source_calibration_method,
            self.target_calibration_method,
            self.source_calibration_evidence,
            self.target_calibration_evidence,
        )
        if any(value is not None for value in calibration_records) and not all(
            value is not None for value in calibration_records
        ):
            raise ValueError("Registration calibration provenance binding requires all four fields")
        for audit_note in (
            self.evidence_note,
            self.independent_review_note,
            self.source_calibration_evidence,
            self.target_calibration_evidence,
        ):
            if audit_note is not None and not audit_note.strip():
                raise ValueError("Registration audit evidence and review notes cannot be blank")
        review_fields = (
            self.independent_reviewer_id,
            self.independent_review_decision,
            self.independent_review_note,
        )
        if any(value is not None for value in review_fields) and not all(
            value is not None for value in review_fields
        ):
            raise ValueError(
                "Independent registration review requires reviewer, decision, and note"
            )
        if self.independent_reviewed_at_utc is not None and self.independent_reviewer_id is None:
            raise ValueError("Dated registration review requires an attributed reviewer")
        if self.independent_reviewer_id is not None and self.registration_operator_id is None:
            raise ValueError("Independent registration review requires operator attribution")
        if (
            self.independent_reviewer_id is not None
            and self.independent_reviewer_id == self.registration_operator_id
        ):
            raise ValueError("Registration reviewer must differ from registration operator")
        transform = self.source_to_target_transform_m
        centroid_bounds = (
            self.source_centroid_position_error_bound_m,
            self.target_centroid_position_error_bound_m,
            self.registration_alignment_error_bound_m,
        )
        if any(bound is not None for bound in centroid_bounds) and (
            transform is None or any(bound is None for bound in centroid_bounds)
        ):
            raise ValueError(
                "Centroid separation bounds require a transform and all three error bounds"
            )
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

    # Optional project binding prevents reuse of otherwise identical local
    # observation labels in a different research project. Legacy evidence is flagged.
    project_id: str | None = Field(default=None, min_length=1, max_length=128)

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

    # An optional, separately attributed human review is an audit record.
    # Even a supporting decision does not certify biological identity.
    independent_reviewer_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    independent_review_decision: (
        Literal["supports_match", "disputes_match", "inconclusive"] | None
    ) = None
    independent_review_note: str | None = Field(default=None, min_length=1, max_length=2_000)
    # Optional audit time; an undated legacy review stays provisional and flagged.
    independent_reviewed_at_utc: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_complete_geometry_binding(self) -> MeshReidentificationEvidence:
        if (self.before_geometry_sha256 is None) != (self.after_geometry_sha256 is None):
            raise ValueError("Reidentification geometry binding requires both SHA-256 fingerprints")
        if (self.before_observed_at_utc is None) != (self.after_observed_at_utc is None):
            raise ValueError("Reidentification timepoint binding requires both UTC timestamps")
        if not self.evidence_note.strip() or (
            self.independent_review_note is not None and not self.independent_review_note.strip()
        ):
            raise ValueError("Reidentification evidence and review notes cannot be blank")
        review_fields = (
            self.independent_reviewer_id,
            self.independent_review_decision,
            self.independent_review_note,
        )
        if any(value is not None for value in review_fields) and not all(
            value is not None for value in review_fields
        ):
            raise ValueError(
                "Independent reidentification review requires reviewer, decision, and note"
            )
        if self.independent_reviewed_at_utc is not None and self.independent_reviewer_id is None:
            raise ValueError("Dated independent review requires a separately attributed reviewer")
        if self.independent_reviewer_id == self.observer_id:
            raise ValueError("Independent reviewer must differ from matching observer")
        return self


class MeshLongitudinalComparisonRequest(BaseModel):
    before: MeshPreviewRequest
    after: MeshPreviewRequest
    registration_evidence: MeshRegistrationEvidence | None = None
    reidentification_evidence: MeshReidentificationEvidence | None = None
