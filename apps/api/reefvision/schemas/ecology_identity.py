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

    @model_validator(mode="after")
    def require_frozen_calibration_snapshot(self) -> EcologyCalibrationEvidenceRow:
        """Bind replayed calibration values to the source image and frozen digest.

        A collection signature alone covers the stored digest, not the
        calibration_json values. Check those values before a saved workflow
        can use them as projected measurement provenance.
        """
        expected = canonical_json_sha256(
            {
                "algorithm_version": "ecology-calibration-source-0001",
                "image_id": self.image_id,
                "image_sha256": self.image_sha256,
                "calibration": self.calibration_json,
            }
        )
        if self.calibration_sha256.lower() != expected:
            raise ValueError("Ecological calibration snapshot fingerprint mismatch")
        return self


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
            for calibration_link in self.calibration_evidence_links:
                if calibration_link.annotation_evidence_id not in annotations:
                    raise ValueError("Ecological registry contains orphan calibration evidence")
                if "image_evidence_links" in self.model_fields_set:
                    annotation_link = annotations[calibration_link.annotation_evidence_id]
                    source = images.get(annotation_link.image_evidence_id)
                    if source is None or (
                        calibration_link.image_id != source.image_id
                        or calibration_link.image_sha256.lower() != source.image_sha256.lower()
                    ):
                        raise ValueError("Ecological registry calibration source image mismatch")

        latest = {row.organism_key: row for row in self.identities}
        if "identity_history" in self.model_fields_set:
            # Present-but-empty history is not the same as a legacy artifact
            # that never stored revision history.
            history_by_key: dict[str, list[EcologyIdentityRow]] = {}
            for identity_revision in self.identity_history:
                history_by_key.setdefault(identity_revision.organism_key, []).append(
                    identity_revision
                )
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

            known_revisions = {(row.organism_key, row.revision) for row in self.identity_history}
            for image_link in self.image_evidence_links:
                if (image_link.organism_key, image_link.identity_revision) not in known_revisions:
                    raise ValueError(
                        "Ecological registry image references unknown identity revision"
                    )
        else:
            # Legacy snapshots may omit the history, but cannot reference
            # nonexistent organisms or future identity revisions.
            for image_link in self.image_evidence_links:
                current = latest.get(image_link.organism_key)
                if (
                    current is None
                    or image_link.identity_revision < 1
                    or image_link.identity_revision > current.revision
                ):
                    raise ValueError(
                        "Ecological registry image references unknown identity revision"
                    )

        # The current-identity signature also protects legacy artifacts
        # which omitted append-only revision history.
        snapshot_rows = [
            {
                "id": row.id,
                "organism_key": row.organism_key,
                "revision": row.revision,
                "kind": row.kind,
                "parent_colony_key": row.parent_colony_key,
                "experimental_unit_type": row.experimental_unit_type,
                "experimental_unit_id": row.experimental_unit_id,
            }
            for row in self.identities
        ]
        expected_snapshot = canonical_json_sha256(
            {
                "schema_version": self.schema_version,
                "project_id": self.project_id,
                "identities": snapshot_rows,
            }
        )
        if self.snapshot_sha256.lower() != expected_snapshot:
            raise ValueError("Ecological registry identity snapshot fingerprint mismatch")

        # Rehydrate the producer's signed image-link collection as well. The
        # metadata-aware v2 digest freezes the source-image capture snapshot;
        # v1 saved artifacts predate that field and can only use the old digest
        # when *every* link is explicitly legacy-unfrozen.
        if (
            "image_evidence_links" in self.model_fields_set
            and self.image_evidence_sha256 is not None
        ):
            image_rows = [
                {
                    "id": row.id,
                    "organism_key": row.organism_key,
                    "identity_revision": row.identity_revision,
                    "image_id": row.image_id,
                    "image_sha256": row.image_sha256,
                    "source_metadata_sha256": row.source_metadata_sha256,
                    "source_metadata_evidence_status": row.source_metadata_evidence_status,
                    "reason": row.reason,
                    "created_at": row.created_at.isoformat(),
                }
                for row in self.image_evidence_links
            ]
            expected_image = canonical_json_sha256(
                {
                    "algorithm_version": "ecology-image-evidence-0002",
                    "project_id": self.project_id,
                    "links": image_rows,
                }
            )
            if self.image_evidence_sha256.lower() != expected_image:
                legacy_rows = [
                    {
                        key: value
                        for key, value in row.items()
                        if key
                        not in (
                            "source_metadata_sha256",
                            "source_metadata_evidence_status",
                        )
                    }
                    for row in image_rows
                ]
                legacy_eligible = all(
                    row.source_metadata_sha256 is None
                    and row.source_metadata_evidence_status == "legacy_unfrozen"
                    for row in self.image_evidence_links
                )
                expected_legacy = canonical_json_sha256(
                    {
                        "algorithm_version": "ecology-image-evidence-0001",
                        "project_id": self.project_id,
                        "links": legacy_rows,
                    }
                )
                if not legacy_eligible or self.image_evidence_sha256.lower() != expected_legacy:
                    raise ValueError("Ecological registry image evidence fingerprint mismatch")

        # Replay must not accept modified signed annotation/calibration links.
        # Missing digests on historical artifacts are not retroactively signed.
        if (
            "annotation_evidence_links" in self.model_fields_set
            and self.annotation_evidence_sha256 is not None
        ):
            annotation_rows = [
                {
                    "id": row.id,
                    "image_evidence_id": row.image_evidence_id,
                    "annotation_kind": row.annotation_kind,
                    "annotation_id": row.annotation_id,
                    "annotation_revision": row.annotation_revision,
                    "annotation_sha256": row.annotation_sha256,
                    "reason": row.reason,
                    "created_at": row.created_at.isoformat(),
                }
                for row in self.annotation_evidence_links
            ]
            expected_annotation = canonical_json_sha256(
                {
                    "algorithm_version": "ecology-annotation-evidence-0001",
                    "project_id": self.project_id,
                    "links": annotation_rows,
                }
            )
            if self.annotation_evidence_sha256.lower() != expected_annotation:
                raise ValueError("Ecological registry annotation evidence fingerprint mismatch")

        if (
            "calibration_evidence_links" in self.model_fields_set
            and self.calibration_evidence_sha256 is not None
        ):
            calibration_rows = [
                {
                    "id": row.id,
                    "annotation_evidence_id": row.annotation_evidence_id,
                    "image_id": row.image_id,
                    "image_sha256": row.image_sha256,
                    "calibration_sha256": row.calibration_sha256,
                    "reason": row.reason,
                    "created_at": row.created_at.isoformat(),
                }
                for row in self.calibration_evidence_links
            ]
            expected_calibration = canonical_json_sha256(
                {
                    "algorithm_version": "ecology-calibration-evidence-0001",
                    "project_id": self.project_id,
                    "links": calibration_rows,
                }
            )
            if self.calibration_evidence_sha256.lower() != expected_calibration:
                raise ValueError("Ecological registry calibration evidence fingerprint mismatch")

        return self

    @model_validator(mode="after")
    def require_derived_design_audit_integrity(self) -> EcologyIdentityRegistryResponse:
        """A saved workflow cannot conceal registered design or parent-unit warnings.

        Derived flags are not signatures of scientific independence. Legacy
        artifacts may omit the audits, but must remain explicitly unavailable.
        """
        # Runtime import avoids a schema/design-audit module import cycle.
        from reefvision.services.ecology_identity_design_audit import (
            derive_cross_unit_parent_details,
            derive_ecology_design_changes,
            derive_historical_cross_unit_parent_details,
        )

        if self.design_history_status == "history_unavailable":
            if self.design_change_count or self.design_change_events:
                raise ValueError("Unavailable ecological design audit contains events")
        else:
            if "identity_history" not in self.model_fields_set:
                raise ValueError("Ecological design audit requires revision history")
            changes = derive_ecology_design_changes(self.identity_history)
            status = "design_changes_require_review" if changes else "no_design_changes_recorded"
            if (
                self.design_history_status != status
                or self.design_change_count != len(changes)
                or self.design_change_events != changes
            ):
                raise ValueError("Ecological design-change audit differs from identity history")

        if self.cross_unit_parent_audit_status == "unavailable":
            if self.cross_unit_shared_parent_colony_keys or self.cross_unit_parent_details:
                raise ValueError("Unavailable ecological parent audit contains findings")
        else:
            details = derive_cross_unit_parent_details(self.identities)
            keys = sorted({row.parent_colony_key for row in details})
            status = "shared_parent_requires_review" if keys else "no_cross_unit_parent_reuse"
            if (
                self.cross_unit_parent_audit_status != status
                or self.cross_unit_shared_parent_colony_keys != keys
                or (
                    "cross_unit_parent_details" in self.model_fields_set
                    and self.cross_unit_parent_details != details
                )
            ):
                raise ValueError("Ecological cross-unit parent audit differs from identities")

        if self.historical_cross_unit_parent_audit_status == "unavailable":
            if self.historical_cross_unit_parent_details:
                raise ValueError("Unavailable ecological historical parent audit contains findings")
        else:
            if "identity_history" not in self.model_fields_set:
                raise ValueError("Ecological historical parent audit requires revision history")
            historical_details = derive_historical_cross_unit_parent_details(self.identity_history)
            status = (
                "recorded_across_units_requires_review"
                if historical_details
                else "no_recorded_cross_unit_parent_reuse"
            )
            if self.historical_cross_unit_parent_audit_status != status or (
                "historical_cross_unit_parent_details" in self.model_fields_set
                and self.historical_cross_unit_parent_details != historical_details
            ):
                raise ValueError("Ecological historical parent audit differs from identity history")
        return self
