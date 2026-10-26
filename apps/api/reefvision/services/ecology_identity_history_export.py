"""Reproducible, unverified CSV export of append-only ecological identity revisions.

The same typed registry is persisted by ecology_identity_registry_source in
saved Workflow Builder runs; export never promotes identities to verified data.
"""

from __future__ import annotations

import csv
import json
from io import StringIO

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_identity import (
    EcologyCrossUnitParentDetail,
    EcologyIdentityRegistryResponse,
)
from reefvision.services.ecology_identity_design_audit import (
    derive_cross_unit_parent_details,
    derive_ecology_design_changes,
)
from reefvision.storage.datasets import canonical_json_sha256


def _spreadsheet_safe(value: str | None) -> str:
    """Prevent user-supplied study labels/reasons becoming spreadsheet formulas."""
    if value is None:
        return ""
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_ecology_identity_history_csv(registry: EcologyIdentityRegistryResponse) -> str:
    """Export every historical assignment after verifying the saved fingerprints.

    Legacy saved workflow artifacts without complete history cannot be
    represented as audited revision exports and are rejected explicitly.
    """
    if registry.history_sha256 is None:
        raise ValidationError("Ecological identity history fingerprint is missing")
    history = sorted(registry.identity_history, key=lambda row: (row.organism_key, row.revision))
    if len(history) != registry.history_revision_count:
        raise ValidationError("Ecological identity history revision count mismatch")

    revisions: dict[str, int] = {}
    latest = {}
    fingerprint_rows = []
    for row in history:
        if row.project_id != registry.project_id:
            raise ValidationError("Ecological identity history has a foreign project record")
        expected = revisions.get(row.organism_key, 0) + 1
        if row.revision != expected:
            raise ValidationError("Ecological identity history has missing or duplicate revisions")
        revisions[row.organism_key] = expected
        latest[row.organism_key] = row
        fingerprint_rows.append(
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
        )
    digest = canonical_json_sha256(
        {
            "algorithm_version": "ecology-identity-history-0001",
            "project_id": registry.project_id,
            "revisions": fingerprint_rows,
        }
    )
    if digest != registry.history_sha256:
        raise ValidationError("Ecological identity history fingerprint mismatch")

    current = {row.organism_key: row for row in registry.identities}
    if len(current) != len(registry.identities) or set(current) != set(latest):
        raise ValidationError("Ecological identity latest-record set does not match history")
    if any(current[key] != row for key, row in latest.items()):
        raise ValidationError("Ecological identity latest record differs from revision history")
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
        for _, row in sorted(current.items())
    ]
    snapshot_digest = canonical_json_sha256(
        {
            "schema_version": "ecology-identity-registry-0001",
            "project_id": registry.project_id,
            "identities": snapshot_rows,
        }
    )
    if snapshot_digest != registry.snapshot_sha256:
        raise ValidationError("Ecological identity latest snapshot fingerprint mismatch")

    # Old saved artifacts remain explicitly unknown, not silently stable.
    if registry.design_history_status != "history_unavailable":
        changes = derive_ecology_design_changes(history)
        expected_status = (
            "design_changes_require_review" if changes else "no_design_changes_recorded"
        )
        if (
            registry.design_change_events != changes
            or registry.design_change_count != len(changes)
            or registry.design_history_status != expected_status
        ):
            raise ValidationError("Ecological design-change audit differs from identity history")

    details: list[EcologyCrossUnitParentDetail] = []
    if registry.cross_unit_parent_audit_status != "unavailable":
        details = derive_cross_unit_parent_details(registry.identities)
        shared_parent_keys = sorted({row.parent_colony_key for row in details})
        expected_status = (
            "shared_parent_requires_review" if shared_parent_keys else "no_cross_unit_parent_reuse"
        )
        if (
            registry.cross_unit_parent_audit_status != expected_status
            or registry.cross_unit_shared_parent_colony_keys != shared_parent_keys
            or (
                "cross_unit_parent_details" in registry.model_fields_set
                and registry.cross_unit_parent_details != details
            )
        ):
            raise ValidationError("Ecological cross-unit parent audit differs from identities")
    elif registry.cross_unit_shared_parent_colony_keys or registry.cross_unit_parent_details:
        raise ValidationError("Unavailable cross-unit parent audit cannot claim reviewed keys")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "project_id",
            "history_sha256",
            "snapshot_sha256",
            "organism_key",
            "revision",
            "kind",
            "parent_colony_key",
            "experimental_unit_type",
            "experimental_unit_id",
            "reason",
            "created_at",
            "evidence_level",
            "review_gate",
            "design_history_status",
            "design_change_count",
            "cross_unit_parent_audit_status",
            "cross_unit_shared_parent_colony_keys",
            "cross_unit_parent_details_json",
        )
    )
    for row in history:
        writer.writerow(
            (
                registry.project_id,
                registry.history_sha256,
                registry.snapshot_sha256,
                _spreadsheet_safe(row.organism_key),
                row.revision,
                row.kind,
                _spreadsheet_safe(row.parent_colony_key),
                _spreadsheet_safe(row.experimental_unit_type),
                _spreadsheet_safe(row.experimental_unit_id),
                _spreadsheet_safe(row.reason),
                row.created_at.isoformat(),
                registry.evidence_level,
                registry.review_gate,
                registry.design_history_status,
                registry.design_change_count,
                registry.cross_unit_parent_audit_status,
                "|".join(registry.cross_unit_shared_parent_colony_keys),
                json.dumps(
                    [detail.model_dump(mode="json") for detail in details],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
    return output.getvalue()
