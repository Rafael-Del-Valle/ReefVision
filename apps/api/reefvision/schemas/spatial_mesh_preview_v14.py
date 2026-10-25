"""Request contract for bounded, unverified 3D mesh measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, model_validator


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
    rms_residual_m: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    correspondence_count: StrictInt = Field(ge=3, le=1_000_000)
    evidence_note: str = Field(min_length=1, max_length=2_000)


class MeshLongitudinalComparisonRequest(BaseModel):
    before: MeshPreviewRequest
    after: MeshPreviewRequest
    registration_evidence: MeshRegistrationEvidence | None = None
