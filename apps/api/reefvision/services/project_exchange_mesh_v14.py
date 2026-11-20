"""Keep archived review receipts intact while rebinding executable mesh IDs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.services.spatial_calibration_review_v14 import (
    canonical_spatial_calibration_review_evidence,
)
from reefvision.services.spatial_mesh_longitudinal_v14 import mesh_review_bundle_sha256
from reefvision.storage.datasets import canonical_json_sha256

MESH_NODE_TYPES = frozenset({"mesh_surface_preview", "mesh_longitudinal_comparison"})
_REVIEW_LINKS = {
    "registration_evidence": (
        "project_id",
        "source_spatial_source_asset_id",
        "target_spatial_source_asset_id",
    ),
    "reidentification_evidence": (
        "project_id",
        "before_spatial_source_asset_id",
        "after_spatial_source_asset_id",
    ),
}


def _remap_links(value: dict[str, Any], links: tuple[str, ...], id_map: dict[str, str]) -> None:
    for key in links:
        identifier = value.get(key)
        if isinstance(identifier, str) and identifier in id_map:
            value[key] = id_map[identifier]


def restore_mesh_parameters(
    node_type: str, parameters: dict[str, Any], id_map: dict[str, str]
) -> dict[str, Any]:
    """Keep researcher-supplied identifiers and evidence literal across import."""
    restored = deepcopy(parameters)
    if node_type == "mesh_surface_preview":
        _remap_links(restored, ("asset_id", "calibration_review_id"), id_map)
        review = restored.get("calibration_review")
        if isinstance(review, dict):
            _remap_links(review, ("reviewed_spatial_source_asset_id",), id_map)
    else:
        for name, links in _REVIEW_LINKS.items():
            review = restored.get(name)
            if isinstance(review, dict):
                _remap_links(review, links, id_map)
    return restored


def restore_mesh_measurement(payload: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    """Localize measurement artifacts for the restored asset inspector."""
    restored = deepcopy(payload)
    _remap_links(restored, ("project_id",), id_map)
    provenance = restored.get("provenance")
    if not isinstance(provenance, dict):
        return restored
    _remap_links(provenance, ("spatial_source_asset_id", "calibration_review_record_id"), id_map)
    review = provenance.get("calibration_review_evidence")
    if isinstance(review, dict):
        _remap_links(review, ("reviewed_spatial_source_asset_id",), id_map)
        if provenance.get("calibration_review_evidence_sha256") is not None:
            try:
                typed = MeshCalibrationReviewEvidence.model_validate(review)
                provenance["calibration_review_evidence_sha256"] = (
                    canonical_spatial_calibration_review_evidence(typed)[1]
                )
            except ValueError as exc:
                raise ValidationError("Mesh exchange calibration receipt is invalid") from exc
    return restored


def validate_mesh_workflow_receipts(sections: dict[str, list[dict[str, Any]]]) -> None:
    """Verify the original measurement and any attached review bundle."""
    for row in sections.get("workflow_artifacts", []):
        if row.get("data_type") != "mesh_longitudinal_comparison":
            continue
        try:
            payload = row["payload_json"]
            if canonical_json_sha256(payload) != row.get("payload_sha256"):
                raise ValidationError("Mesh comparison payload checksum mismatch")
            provenance = payload["provenance"]
            bundle = provenance.get("review_evidence_bundle")
            digest = provenance.get("review_evidence_bundle_sha256")
            if bundle is None and digest is None:
                continue
            valid = (
                isinstance(bundle, dict)
                and bundle.get("project_id") == payload.get("project_id")
                and bundle.get("schema_version")
                == provenance.get("review_evidence_bundle_schema_version")
                and bundle.get("registration_evidence") == provenance.get("registration_evidence")
                and bundle.get("reidentification_evidence")
                == provenance.get("reidentification_evidence")
                and mesh_review_bundle_sha256(bundle) == digest
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Mesh exchange review receipt is invalid") from exc
        if not valid:
            raise ValidationError("Mesh exchange review bundle failed integrity validation")
