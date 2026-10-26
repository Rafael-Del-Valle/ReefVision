"""Strict project-owned ecological identity contracts; no verification claims."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type

Key = str


class EcologyIdentityFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["colony", "fragment", "individual"]
    parent_colony_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    experimental_unit_type: str | None = Field(default=None, max_length=100)
    experimental_unit_id: str | None = Field(default=None, min_length=1, max_length=150)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("experimental_unit_type")
    @classmethod
    def reject_technical_replicates(cls, value: str | None) -> str | None:
        return require_ecological_unit_type(value)

    @model_validator(mode="after")
    def require_complete_unit(self) -> EcologyIdentityFields:
        if (self.experimental_unit_type is None) != (self.experimental_unit_id is None):
            raise ValueError("Experimental unit type and ID must be declared together")
        if self.parent_colony_key is not None and self.kind != "fragment":
            raise ValueError("Only fragments can reference a parent colony")
        return self


class EcologyIdentityCreate(EcologyIdentityFields):
    organism_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class EcologyIdentityRevisionCreate(EcologyIdentityFields):
    expected_revision: int = Field(ge=1)


class EcologyIdentityRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    organism_key: str
    revision: int
    kind: Literal["colony", "fragment", "individual"]
    parent_colony_key: str | None
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    reason: str
    created_at: datetime


class EcologyImageEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str = Field(min_length=1, max_length=36)
    expected_identity_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class EcologyImageEvidenceRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    organism_key: str
    identity_revision: int
    image_id: str
    image_sha256: str
    reason: str
    created_at: datetime
    evidence_level: Literal["linked_unverified"] = "linked_unverified"


class EcologyAnnotationEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_evidence_id: str = Field(min_length=1, max_length=36)
    annotation_kind: Literal["box", "mask"]
    annotation_id: str = Field(min_length=1, max_length=36)
    expected_annotation_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class EcologyAnnotationEvidenceRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    image_evidence_id: str
    annotation_kind: Literal["box", "mask"]
    annotation_id: str
    annotation_revision: int
    annotation_sha256: str
    reason: str
    created_at: datetime
    evidence_level: Literal["linked_unverified"] = "linked_unverified"


class EcologyCalibrationEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_evidence_id: str = Field(min_length=36, max_length=36)
    expected_annotation_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    confirm_source_calibration: Literal[True]
    reason: str = Field(min_length=3, max_length=500)


class EcologyCalibrationEvidenceRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    annotation_evidence_id: str
    image_id: str
    image_sha256: str
    calibration_json: dict[str, Any]
    calibration_sha256: str
    reason: str
    created_at: datetime
    evidence_level: Literal["linked_unverified"] = "linked_unverified"


EcologyDesignChangedField = Literal[
    "kind", "parent_colony_key", "experimental_unit_type", "experimental_unit_id"
]


class EcologyDesignRevisionChange(BaseModel):
    """An unverified experimental-design or lineage revision."""

    model_config = ConfigDict(extra="forbid")

    organism_key: str
    from_revision: int = Field(ge=1)
    to_revision: int = Field(ge=2)
    changed_fields: list[EcologyDesignChangedField] = Field(min_length=1)
    previous_kind: Literal["colony", "fragment", "individual"]
    current_kind: Literal["colony", "fragment", "individual"]
    previous_parent_colony_key: str | None
    current_parent_colony_key: str | None
    previous_experimental_unit_type: str | None
    previous_experimental_unit_id: str | None
    current_experimental_unit_type: str | None
    current_experimental_unit_id: str | None


class EcologyIdentityRegistryResponse(BaseModel):
    schema_version: Literal["ecology-identity-registry-0001"] = "ecology-identity-registry-0001"
    project_id: str
    identities: list[EcologyIdentityRow]
    snapshot_sha256: str
    image_evidence_links: list[EcologyImageEvidenceRow] = Field(default_factory=list)
    image_evidence_count: int = 0
    image_evidence_sha256: str | None = None
    annotation_evidence_links: list[EcologyAnnotationEvidenceRow] = Field(default_factory=list)
    annotation_evidence_count: int = 0
    annotation_evidence_sha256: str | None = None
    calibration_evidence_links: list[EcologyCalibrationEvidenceRow] = Field(default_factory=list)
    calibration_evidence_count: int = 0
    calibration_evidence_sha256: str | None = None
    # The complete append-only revision trail is reviewable, including superseded
    # experimental-unit assignments. Older workflow artifacts decode as [].
    identity_history: list[EcologyIdentityRow] = Field(default_factory=list)
    # Optional defaults preserve deserialization of earlier persisted artifacts.
    history_sha256: str | None = None
    history_revision_count: int = 0
    # Legacy saved artifacts cannot claim a stable design without a derived audit.
    design_history_status: Literal[
        "history_unavailable", "no_design_changes_recorded", "design_changes_require_review"
    ] = "history_unavailable"
    design_change_count: int = Field(default=0, ge=0)
    design_change_events: list[EcologyDesignRevisionChange] = Field(default_factory=list)
    evidence_level: Literal["registered_unverified"] = "registered_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"
