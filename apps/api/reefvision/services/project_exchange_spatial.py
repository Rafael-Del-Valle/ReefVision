"""Validate immutable spatial source and review records before exchange remapping."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from reefvision.domain.errors import ValidationError
from reefvision.schemas.spatial_asset_metadata_revision_v14 import (
    SpatialAssetMetadataRevisionCreate,
)
from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.schemas.spatial_source_asset_v14 import SpatialSourceParseResult
from reefvision.services.spatial_asset_metadata_revisions_v14 import (
    spatial_asset_metadata_content,
)
from reefvision.services.spatial_calibration_review_v14 import (
    canonical_spatial_calibration_review_evidence,
)
from reefvision.services.spatial_source_assets_v14 import (
    SPATIAL_PARSE_JOB,
    SPATIAL_PARSE_SCHEMA,
    spatial_source_parse_result_content,
)
from reefvision.storage.datasets import canonical_json_sha256


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

    metadata_ids: set[str] = set()
    revisions_by_asset: dict[str, list[dict[str, Any]]] = {}
    for row in sections.get("spatial_asset_metadata_revisions", []):
        revision_id = row.get("id")
        asset_id = row.get("spatial_source_asset_id")
        asset = assets.get(str(asset_id))
        if (
            not isinstance(revision_id, str)
            or not revision_id
            or revision_id in metadata_ids
            or row.get("project_id") != project_id
            or asset is None
            or row.get("source_sha256") != asset.get("sha256")
            or type(row.get("revision")) is not int
            or row["revision"] <= 0
        ):
            raise ValidationError("Spatial asset metadata source binding is invalid")
        try:
            payload = SpatialAssetMetadataRevisionCreate.model_validate(
                {
                    "coordinate_unit": row.get("coordinate_unit"),
                    "meters_per_unit": row.get("meters_per_unit"),
                    "coordinate_frame_id": row.get("coordinate_frame_id"),
                    "transform_to_project_frame": row.get("transform_to_project_frame_json"),
                    "calibration_evidence": row.get("calibration_evidence"),
                    "review_state": row.get("review_state"),
                    "reviewed_by_identity": row.get("reviewed_by_identity"),
                    "review_note": row.get("review_note"),
                    "created_by_identity": row.get("created_by_identity"),
                }
            )
        except (PydanticValidationError, ValueError) as exc:
            raise ValidationError("Spatial asset metadata evidence is invalid") from exc
        content = spatial_asset_metadata_content(
            project_id=project_id,
            asset_id=str(asset_id),
            source_sha256=str(asset["sha256"]),
            revision=row["revision"],
            previous_revision_id=row.get("previous_revision_id"),
            payload=payload,
        )
        if canonical_json_sha256(content) != row.get("content_sha256"):
            raise ValidationError("Spatial asset metadata evidence failed integrity validation")
        metadata_ids.add(revision_id)
        revisions_by_asset.setdefault(str(asset_id), []).append(row)

    for rows in revisions_by_asset.values():
        ordered = sorted(rows, key=lambda item: item["revision"])
        for index, row in enumerate(ordered, start=1):
            expected_previous = None if index == 1 else ordered[index - 2]["id"]
            if row["revision"] != index or row.get("previous_revision_id") != expected_previous:
                raise ValidationError("Spatial asset metadata revision chain is invalid")

    for row in sections.get("jobs", []):
        if row.get("job_type") != SPATIAL_PARSE_JOB:
            continue
        request = row.get("request_json")
        asset_id = request.get("spatial_source_asset_id") if isinstance(request, dict) else None
        asset = assets.get(str(asset_id))
        if (
            row.get("project_id") != project_id
            or not isinstance(request, dict)
            or request.get("schema_version") != SPATIAL_PARSE_SCHEMA
            or request.get("project_id") != project_id
            or asset is None
            or request.get("expected_source_sha256") != asset.get("sha256")
            or request.get("source_format") != asset.get("source_format")
            or request.get("size_bytes") != asset.get("size_bytes")
        ):
            raise ValidationError("Spatial source parse job binding is invalid")
        result_json = row.get("result_json")
        if row.get("status") == "succeeded":
            try:
                result = SpatialSourceParseResult.model_validate(result_json)
            except (PydanticValidationError, ValueError) as exc:
                raise ValidationError("Spatial source parse result is invalid") from exc
            if (
                result.project_id != project_id
                or result.spatial_source_asset_id != asset_id
                or result.source_sha256 != asset.get("sha256")
                or result.source_format != asset.get("source_format")
                or canonical_json_sha256(spatial_source_parse_result_content(result))
                != result.content_sha256
            ):
                raise ValidationError("Spatial source parse result failed integrity validation")
        elif result_json is not None:
            raise ValidationError("Incomplete spatial source parse job cannot carry a result")
