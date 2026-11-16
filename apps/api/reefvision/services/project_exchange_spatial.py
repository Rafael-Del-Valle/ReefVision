"""Validate immutable spatial source and review records before exchange remapping."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from reefvision.domain.errors import ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.services.spatial_calibration_review_v14 import (
    canonical_spatial_calibration_review_evidence,
)


def validate_spatial_exchange_records(
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
) -> None:
    """Reject altered source bindings or review receipts before ID remapping."""

    assets: dict[str, dict[str, Any]] = {}
    for row in sections.get("spatial_source_assets", []):
        asset_id = row.get("id")
        digest = row.get("sha256")
        size_bytes = row.get("size_bytes")
        if (
            not isinstance(asset_id, str)
            or not asset_id
            or row.get("project_id") != project_id
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or type(size_bytes) is not int
            or size_bytes <= 0
            or asset_id in assets
        ):
            raise ValidationError("Spatial source exchange record is invalid")
        assets[asset_id] = row

    review_ids: set[str] = set()
    for row in sections.get("spatial_calibration_reviews", []):
        review_id = row.get("id")
        asset_id = row.get("spatial_source_asset_id")
        asset = assets.get(str(asset_id))
        if (
            not isinstance(review_id, str)
            or not review_id
            or review_id in review_ids
            or row.get("project_id") != project_id
            or asset is None
            or row.get("source_sha256") != asset.get("sha256")
        ):
            raise ValidationError("Spatial calibration review source binding is invalid")
        try:
            evidence = MeshCalibrationReviewEvidence.model_validate(row.get("evidence_json"))
            _, digest = canonical_spatial_calibration_review_evidence(evidence)
        except (PydanticValidationError, ValueError) as exc:
            raise ValidationError("Spatial calibration review evidence is invalid") from exc
        if (
            digest != row.get("evidence_sha256")
            or evidence.reviewed_spatial_source_asset_id != asset_id
            or evidence.reviewed_source_payload_sha256 != asset.get("sha256")
        ):
            raise ValidationError("Spatial calibration review evidence failed integrity validation")
        review_ids.add(review_id)
