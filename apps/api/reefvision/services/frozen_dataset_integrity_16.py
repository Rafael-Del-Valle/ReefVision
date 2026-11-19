"""Validate immutable image-level evidence before standalone or saved frozen QC.

A saved Workflow Builder reference and aggregate count can both remain valid
after the original biological annotation coordinates were altered in a dataset
version row. The separately persisted manifest provides the original per-image
content and SHA-256, without consulting mutable live annotations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256


def _item_payload(item: DatasetVersionItem) -> dict[str, Any]:
    """Reproduce the immutable item contract saved by DatasetVersionService."""
    return {
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


def validate_frozen_dataset_manifest(
    version: DatasetVersion, items: Sequence[DatasetVersionItem]
) -> None:
    """Fail closed on altered frozen rows, never repair or modify study data.

    This validates the stored detection-snapshot format used by current
    dataset versions. A future format including frozen masks must extend the
    contract explicitly; do not infer unseen mask truth from live annotations.
    """
    manifest = version.manifest_json
    message = "Frozen dataset item snapshot does not match its original manifest"
    if (
        not isinstance(manifest, dict)
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
    if (
        not isinstance(manifest.get("summary"), dict)
        or manifest["summary"].get("image_count") != version.image_count
        or manifest["summary"].get("annotation_count") != version.annotation_count
        or sum(item.annotation_count for item in items) != version.annotation_count
        or sum(item.mask_annotation_count for item in items) != version.mask_annotation_count
    ):
        raise ValidationError(message)
    seen: set[str] = set()
    for item in items:
        if item.image_id in seen:
            raise ValidationError(message)
        seen.add(item.image_id)
        payload = _item_payload(item)
        # A mask-bearing schema must have its own complete, signed mask
        # contract. This legacy manifest contains only detection annotations.
        if (
            item.mask_annotation_count != 0
            or item.mask_annotation_snapshot_json
            or canonical_json_sha256(payload) != item.snapshot_sha256
            or entries.get(item.image_id)
            != {**payload, "snapshot_sha256": item.snapshot_sha256}
        ):
            raise ValidationError(message)
