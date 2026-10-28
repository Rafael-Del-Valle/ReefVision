"""Strict project-owned ecological identity contracts; no verification claims."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.storage.datasets import canonical_json_sha256

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
    image_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    # Optional defaults keep earlier saved Workflow Builder registry artifacts readable.
    source_metadata_sha256: str | None = None
    source_metadata_evidence_status: Literal["frozen", "legacy_unfrozen"] = "legacy_unfrozen"
    reason: str
    created_at: datetime
    evidence_level: Literal["linked_unverified"] = "linked_unverified"

    @model_validator(mode="after")
    def require_consistent_source_metadata_status(self) -> EcologyImageEvidenceRow:
        """A replayed legacy link cannot masquerade as frozen source evidence."""
        digest = self.source_metadata_sha256
        if digest is not None and re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            raise ValueError("Image source metadata fingerprint must be SHA-256")
        if (digest is None) != (self.source_metadata_evidence_status == "legacy_unfrozen"):
            raise ValueError("Image source metadata evidence status contradicts its fingerprint")
        return self


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
    annotation_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
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
    image_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    calibration_json: dict[str, Any]
    calibration_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
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


class EcologyCrossUnitParentDetail(BaseModel):
    """Registered shared-parent evidence at one declared sampling level."""

    model_config = ConfigDict(extra="forbid")

    parent_colony_key: str
    experimental_unit_level: str
    experimental_unit_ids: list[str] = Field(min_length=2)
    fragment_keys: list[str] = Field(min_length=2)


class EcologyHistoricalParentAssignment(BaseModel):
    """One unverified identity revision recording a fragment in a declared unit."""

    model_config = ConfigDict(extra="forbid")

    organism_key: str
    identity_revision: int = Field(ge=1)
    experimental_unit_type: str
    experimental_unit_id: str


class EcologyHistoricalCrossUnitParentDetail(BaseModel):
    """Historical registrations, not proof of simultaneous occupancy or movement."""

    model_config = ConfigDict(extra="forbid")

    parent_colony_key: str
    experimental_unit_level: str
    experimental_unit_ids: list[str] = Field(min_length=2)
    assignments: list[EcologyHistoricalParentAssignment] = Field(min_length=2)


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
    # Legacy workflow artifacts cannot assert that a parent stayed in one unit.
    cross_unit_parent_audit_status: Literal[
        "unavailable", "no_cross_unit_parent_reuse", "shared_parent_requires_review"
    ] = "unavailable"
    cross_unit_shared_parent_colony_keys: list[str] = Field(default_factory=list)
    # Actionable, deterministic review evidence; absent in older saved artifacts.
    cross_unit_parent_details: list[EcologyCrossUnitParentDetail] = Field(default_factory=list)
    # Earlier revisions can record units no longer present in the latest snapshot.
    # This is a historical registration warning, NOT an observed movement event.
    historical_cross_unit_parent_audit_status: Literal[
        "unavailable",
        "no_recorded_cross_unit_parent_reuse",
        "recorded_across_units_requires_review",
    ] = "unavailable"
    historical_cross_unit_parent_details: list[EcologyHistoricalCrossUnitParentDetail] = Field(
        default_factory=list
    )
    evidence_level: Literal["registered_unverified"] = "registered_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"

    @model_validator(mode="after")
    def require_linked_evidence_integrity(self) -> EcologyIdentityRegistryResponse:
        """Reject cross-project, orphaned or duplicated persisted source evidence.

        Older artifacts may omit later-added link collections or counts.
        Only enforce relationships for fields actually present in a snapshot.
        This does not authenticate the underlying source bytes.
        """
        for collection in (
            "identities",
            "identity_history",
            "image_evidence_links",
            "annotation_evidence_links",
            "calibration_evidence_links",
        ):
            rows = getattr(self, collection)
            if any(row.project_id != self.project_id for row in rows):
                raise ValueError("Ecological registry contains cross-project evidence")
            keys = [
                (row.organism_key, row.revision)
                if collection == "identity_history"
                else row.organism_key
                if collection == "identities"
                else row.id
                for row in rows
            ]
            if len(keys) != len(set(keys)):
                raise ValueError("Ecological registry contains duplicate evidence identities")

        for collection, count_field in (
            ("image_evidence_links", "image_evidence_count"),
            ("annotation_evidence_links", "annotation_evidence_count"),
            ("calibration_evidence_links", "calibration_evidence_count"),
            ("identity_history", "history_revision_count"),
        ):
            if (
                collection in self.model_fields_set
                and count_field in self.model_fields_set
                and getattr(self, count_field) != len(getattr(self, collection))
            ):
                raise ValueError("Ecological registry evidence count contradicts its links")

        images = {row.id: row for row in self.image_evidence_links}
        annotations = {row.id: row for row in self.annotation_evidence_links}
        if "image_evidence_links" in self.model_fields_set:
            for row in self.annotation_evidence_links:
                if row.image_evidence_id not in images:
                    raise ValueError("Ecological registry contains orphan annotation evidence")
        if "annotation_evidence_links" in self.model_fields_set:
            for row in self.calibration_evidence_links:
                if row.annotation_evidence_id not in annotations:
                    raise ValueError("Ecological registry contains orphan calibration evidence")
                if "image_evidence_links" in self.model_fields_set:
                    source = images.get(annotations[row.annotation_evidence_id].image_evidence_id)
                    if source is None or (
                        row.image_id != source.image_id
                        or row.image_sha256.lower() != source.image_sha256.lower()
                    ):
                        raise ValueError("Ecological registry calibration source image mismatch")

        latest = {row.organism_key: row for row in self.identities}
        if "identity_history" in self.model_fields_set:
            # Present-but-empty history is not the same as a legacy artifact
            # that never stored revision history.
            history_by_key: dict[str, list[EcologyIdentityRow]] = {}
            for row in self.identity_history:
                history_by_key.setdefault(row.organism_key, []).append(row)
            if set(history_by_key) != set(latest):
                raise ValueError(
                    "Ecological registry latest identities contradict revision history"
                )
            for organism_key, rows in history_by_key.items():
                ordered = sorted(rows, key=lambda row: row.revision)
                if [row.revision for row in ordered] != list(range(1, len(ordered) + 1)):
                    raise ValueError("Ecological registry revision history is not contiguous")
                if ordered[-1] != latest[organism_key]:
                    raise ValueError(
                        "Ecological registry latest identity contradicts revision history"
                    )

            if self.history_sha256 is not None:
                # Recheck the existing producer's canonical history digest.
                # A digest proves internal consistency, not external authorship.
                history_rows = [
                    {
                        "id": row.id,
                        "organism_key": row.organism_key,
                        "revision": row.revision,
                        "kind": row.kind,
                        "parent_colony_key": row.parent_colony_key,
                        "experimental_unit_type": row.experimental_unit_type,
                        "experimental_unit_id": row.experimental_unit_id,
                        "reason": row.reason,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in self.identity_history
                ]
                expected = canonical_json_sha256(
                    {
                        "algorithm_version": "ecology-identity-history-0001",
                        "project_id": self.project_id,
                        "revisions": history_rows,
                    }
                )
                if self.history_sha256.lower() != expected:
                    raise ValueError("Ecological registry history fingerprint mismatch")

            known_revisions = {
                (row.organism_key, row.revision) for row in self.identity_history
            }
            for row in self.image_evidence_links:
                if (row.organism_key, row.identity_revision) not in known_revisions:
                    raise ValueError(
                        "Ecological registry image references unknown identity revision"
                    )
        else:
            # Legacy snapshots may omit the history, but cannot reference
            # nonexistent organisms or future identity revisions.
            for row in self.image_evidence_links:
                current = latest.get(row.organism_key)
                if (
                    current is None
                    or row.identity_revision < 1
                    or row.identity_revision > current.revision
                ):
                    raise ValueError(
                        "Ecological registry image references unknown identity revision"
                    )
        return self
