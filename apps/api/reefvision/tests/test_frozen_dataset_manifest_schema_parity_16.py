"""Original 0006 and mask-aware 0007 frozen manifests share the QC integrity gate."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest

from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.domain.errors import ValidationError
from reefvision.services.frozen_dataset_integrity_16 import (
    _item_payload,
    validate_frozen_dataset_manifest,
)
from reefvision.storage.datasets import canonical_json_sha256


def _saved_snapshot(
    schema_version: str, *, with_mask: bool
) -> tuple[DatasetVersion, DatasetVersionItem]:
    mask = {
        "id": "mask-1",
        "label_class_id": "swiftia",
        "geometry_kind": "polygon",
        "vertices": [[2, 3], [4, 3], [3, 5]],
        "measurement_json": {"length_mm": 4.5},
    }
    masks = [mask] if with_mask else []
    item = cast(
        DatasetVersionItem,
        SimpleNamespace(
            image_id="image-1",
            image_sha256="a" * 64,
            original_filename="swiftia.png",
            width_px=100,
            height_px=100,
            image_annotation_status="reviewed",
            split="train",
            group_key="parent-fragment-1",
            annotation_count=1,
            per_class_counts_json={"swiftia": 1},
            annotation_snapshot_json=[
                {"id": "polyp-1", "label_class_id": "swiftia", "x_min": 5, "y_min": 6, "x_max": 10, "y_max": 12}
            ],
            mask_annotation_count=len(masks),
            per_mask_class_counts_json={"swiftia": 1} if with_mask else {},
            mask_annotation_snapshot_json=masks,
            snapshot_sha256="",
        ),
    )
    payload = _item_payload(item, schema_version=schema_version)
    item.snapshot_sha256 = canonical_json_sha256(payload)
    summary = {"image_count": 1, "annotation_count": 1}
    if schema_version == "0007":
        summary["mask_annotation_count"] = len(masks)
    manifest = {
        "schema_version": schema_version,
        "summary": summary,
        "items": [{**payload, "snapshot_sha256": item.snapshot_sha256}],
    }
    version = cast(
        DatasetVersion,
        SimpleNamespace(
            schema_version=schema_version,
            manifest_json=manifest,
            manifest_sha256=canonical_json_sha256(manifest),
            image_count=1,
            annotation_count=1,
            mask_annotation_count=len(masks),
        ),
    )
    return version, item


@pytest.mark.parametrize(
    ("schema_version", "with_mask"),
    [("0006", False), ("0007", False), ("0007", True)],
)
def test_original_frozen_manifest_formats_remain_valid(
    schema_version: str, with_mask: bool
) -> None:
    version, item = _saved_snapshot(schema_version, with_mask=with_mask)
    validate_frozen_dataset_manifest(version, [item])


@pytest.mark.parametrize(
    "tamper",
    [
        "resigned_mask_geometry",
        "resigned_mask_measurement",
        "mask_count",
        "mask_class_count",
        "schema_downgrade",
        "missing_mask_summary",
        "resigned_detection_geometry",
    ],
)
def test_mask_aware_frozen_manifest_rejects_corrupt_or_resigned_evidence(tamper: str) -> None:
    version, item = _saved_snapshot("0007", with_mask=True)
    if tamper == "resigned_mask_geometry":
        item.mask_annotation_snapshot_json = deepcopy(item.mask_annotation_snapshot_json)
        item.mask_annotation_snapshot_json[0]["vertices"][0][0] = 71
    elif tamper == "resigned_mask_measurement":
        item.mask_annotation_snapshot_json = deepcopy(item.mask_annotation_snapshot_json)
        item.mask_annotation_snapshot_json[0]["measurement_json"]["length_mm"] = 99.0
    elif tamper == "mask_count":
        item.mask_annotation_count = 2
    elif tamper == "mask_class_count":
        item.per_mask_class_counts_json = {"other_species": 1}
    elif tamper == "schema_downgrade":
        version.manifest_json = deepcopy(version.manifest_json)
        version.manifest_json["schema_version"] = "0006"
        version.manifest_sha256 = canonical_json_sha256(version.manifest_json)
    elif tamper == "missing_mask_summary":
        version.manifest_json = deepcopy(version.manifest_json)
        version.manifest_json["summary"].pop("mask_annotation_count")
        version.manifest_sha256 = canonical_json_sha256(version.manifest_json)
    else:
        item.annotation_snapshot_json = deepcopy(item.annotation_snapshot_json)
        item.annotation_snapshot_json[0]["x_min"] = 51
    if tamper.startswith("resigned_"):
        item.snapshot_sha256 = canonical_json_sha256(_item_payload(item, schema_version="0007"))
    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [item])


def test_legacy_frozen_manifest_cannot_gain_untracked_mask_evidence() -> None:
    version, item = _saved_snapshot("0006", with_mask=False)
    item.mask_annotation_count = 1
    item.mask_annotation_snapshot_json = [{"id": "mask-1", "label_class_id": "swiftia"}]
    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [item])


@pytest.mark.parametrize(
    ("schema_version", "with_mask"),
    [("0006", False), ("0007", False), ("0007", True)],
)
def test_fully_resigned_duplicate_observation_id_fails_all_original_schemas(
    schema_version: str, with_mask: bool
) -> None:
    """A second biological detection cannot reuse the first annotation ID."""
    version, item = _saved_snapshot(schema_version, with_mask=with_mask)
    original = dict(item.annotation_snapshot_json[0])
    item.annotation_snapshot_json = [original, dict(original)]
    item.annotation_count = 2
    item.per_class_counts_json = {"swiftia": 2}
    version.annotation_count = 2
    manifest = deepcopy(version.manifest_json)
    manifest["summary"]["annotation_count"] = 2
    payload = _item_payload(item, schema_version=schema_version)
    item.snapshot_sha256 = canonical_json_sha256(payload)
    manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)

    # Every digest and aggregate count agrees; observation identity does not.
    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [item])


@pytest.mark.parametrize("tamper", ["missing", "empty", "duplicate"])
def test_fully_resigned_mask_observation_identity_is_unique(tamper: str) -> None:
    """A checksummed polygon mask must still identify one distinct observation."""
    version, item = _saved_snapshot("0007", with_mask=True)
    masks = deepcopy(item.mask_annotation_snapshot_json)
    if tamper == "missing":
        masks[0].pop("id")
    elif tamper == "empty":
        masks[0]["id"] = ""
    else:
        masks.append(deepcopy(masks[0]))
        item.mask_annotation_count = 2
        item.per_mask_class_counts_json = {"swiftia": 2}
        version.mask_annotation_count = 2
    item.mask_annotation_snapshot_json = masks

    payload = _item_payload(item, schema_version="0007")
    item.snapshot_sha256 = canonical_json_sha256(payload)
    manifest = deepcopy(version.manifest_json)
    manifest["summary"]["mask_annotation_count"] = version.mask_annotation_count
    manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)

    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [item])


def test_resigned_mask_identity_cannot_be_reused_across_frozen_images() -> None:
    """Two different images cannot claim the same original mask row."""
    version, first = _saved_snapshot("0007", with_mask=True)
    second = deepcopy(first)
    second.image_id = "image-2"
    second.image_sha256 = "b" * 64
    second.original_filename = "swiftia-second.png"
    second.annotation_snapshot_json[0]["id"] = "polyp-2"
    # Deliberately retain the first image's mask ID; all other data are valid.
    first_payload = _item_payload(first, schema_version="0007")
    second_payload = _item_payload(second, schema_version="0007")
    second.snapshot_sha256 = canonical_json_sha256(second_payload)
    version.image_count = 2
    version.annotation_count = 2
    version.mask_annotation_count = 2
    manifest = deepcopy(version.manifest_json)
    manifest["summary"] = {
        "image_count": 2,
        "annotation_count": 2,
        "mask_annotation_count": 2,
    }
    manifest["items"] = [
        {**first_payload, "snapshot_sha256": first.snapshot_sha256},
        {**second_payload, "snapshot_sha256": second.snapshot_sha256},
    ]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)

    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [first, second])


@pytest.mark.parametrize("schema_version", ["0006", "0007"])
@pytest.mark.parametrize(
    "tamper",
    ["negative", "zero_area", "outside_image", "nonfinite", "text", "boolean"],
)
def test_fully_resigned_invalid_detection_geometry_fails_original_schemas(
    schema_version: str, tamper: str
) -> None:
    """Checksums cannot turn an impossible source-pixel region into a coral."""
    version, item = _saved_snapshot(schema_version, with_mask=False)
    snapshot = deepcopy(item.annotation_snapshot_json[0])
    if tamper == "negative":
        snapshot["x_min"] = -1.0
    elif tamper == "zero_area":
        snapshot["x_max"] = snapshot["x_min"]
    elif tamper == "outside_image":
        snapshot["y_max"] = item.height_px + 1.0
    elif tamper == "nonfinite":
        snapshot["x_min"] = float("inf")
    elif tamper == "text":
        snapshot["y_min"] = "6"
    else:
        snapshot["y_min"] = True
    item.annotation_snapshot_json = [snapshot]

    payload = _item_payload(item, schema_version=schema_version)
    item.snapshot_sha256 = canonical_json_sha256(payload)
    manifest = deepcopy(version.manifest_json)
    manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)

    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [item])
