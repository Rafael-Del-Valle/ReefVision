"""Validate immutable image-level evidence before standalone or saved frozen QC.

A saved Workflow Builder reference and aggregate count can both remain valid
after original biological annotations were altered in a dataset-version row.
The separately persisted manifest provides the original per-image content and
SHA-256 without consulting mutable live annotations.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256

# The API currently writes mask/measurement-aware 0007 manifests, including
# when there are no masks. Historical detection-only 0006 snapshots also exist.
SUPPORTED_SNAPSHOT_SCHEMAS = frozenset({"0006", "0007"})


def _item_payload(item: DatasetVersionItem, *, schema_version: str) -> dict[str, Any]:
    """Reconstruct exactly the schema recorded by the version's producer."""
    payload: dict[str, Any] = {
        "image_id": item.image_id,
        "image_sha256": item.image_sha256,
        "original_filename": item.original_filename,
        "width_px": item.width_px,
        "height_px": item.height_px,
        "annotation_status": item.image_annotation_status,
        "split": item.split,
        "group_key": item.group_key,
        "annotation_count": item.annotation_count,
        "per_class_counts": item.per_class_counts_json,
        "annotations": item.annotation_snapshot_json,
    }
    if schema_version == "0007":
        # Preserve original polygon/raster and optional measurement metadata
        # verbatim. No current live mask or measurement can enter frozen QC.
        payload.update(
            {
                "mask_annotation_count": item.mask_annotation_count,
                "per_mask_class_counts": item.per_mask_class_counts_json,
                "mask_annotations": item.mask_annotation_snapshot_json,
            }
        )
    return payload


def validate_frozen_dataset_manifest(
    version: DatasetVersion, items: Sequence[DatasetVersionItem]
) -> None:
    """Fail closed on changed frozen rows, without repairing study data.

    Respect the original 0006 detection-only and 0007 mask-aware manifest
    contracts. An unsupported schema needs its own scientific validator.
    """
    manifest = version.manifest_json
    message = "Frozen dataset item snapshot does not match its original manifest"
    if not isinstance(manifest, dict):
        raise ValidationError(message)
    schema_version = manifest.get("schema_version")
    if (
        type(schema_version) is not str
        or schema_version not in SUPPORTED_SNAPSHOT_SCHEMAS
        or schema_version != version.schema_version
        or canonical_json_sha256(manifest) != version.manifest_sha256
        or not isinstance(manifest.get("items"), list)
        or len(manifest["items"]) != len(items)
        or len(items) != version.image_count
    ):
        raise ValidationError(message)

    entries: dict[str, dict[str, Any]] = {}
    for record in manifest["items"]:
        if (
            not isinstance(record, dict)
            or type(record.get("image_id")) is not str
            or not record["image_id"]
            or record["image_id"] in entries
        ):
            raise ValidationError(message)
        entries[record["image_id"]] = record

    summary = manifest.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("image_count") != version.image_count
        or summary.get("annotation_count") != version.annotation_count
        or sum(item.annotation_count for item in items) != version.annotation_count
        or sum(item.mask_annotation_count for item in items) != version.mask_annotation_count
        or (
            schema_version == "0007"
            and summary.get("mask_annotation_count") != version.mask_annotation_count
        )
        or (schema_version == "0006" and version.mask_annotation_count != 0)
    ):
        raise ValidationError(message)

    seen: set[str] = set()
    for item in items:
        if item.image_id in seen:
            raise ValidationError(message)
        seen.add(item.image_id)
        if schema_version == "0006":
            # A legacy manifest cannot legitimately authorize masks omitted
            # from its historical per-image SHA-256 payload.
            if (
                item.mask_annotation_count != 0
                or item.mask_annotation_snapshot_json
                or item.per_mask_class_counts_json
            ):
                raise ValidationError(message)
        else:
            mask_snapshots = item.mask_annotation_snapshot_json
            if (
                type(item.mask_annotation_count) is not int
                or not isinstance(mask_snapshots, list)
                or item.mask_annotation_count != len(mask_snapshots)
                or any(
                    not isinstance(snapshot, dict)
                    or type(snapshot.get("label_class_id")) is not str
                    for snapshot in mask_snapshots
                )
                or item.per_mask_class_counts_json
                != dict(Counter(snapshot["label_class_id"] for snapshot in mask_snapshots))
            ):
                raise ValidationError(message)

        payload = _item_payload(item, schema_version=schema_version)
        if canonical_json_sha256(payload) != item.snapshot_sha256 or entries.get(item.image_id) != {
            **payload,
            "snapshot_sha256": item.snapshot_sha256,
        }:
            raise ValidationError(message)
