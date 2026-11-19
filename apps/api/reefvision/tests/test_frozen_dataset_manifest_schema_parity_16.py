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
        "status": "verified",
        # Match the original 0007 producer's source-pixel polygon contract.
        "polygon_json": [[2, 3], [4, 3], [3, 5]],
        "x_min": 2,
        "y_min": 3,
        "x_max": 4,
        "y_max": 5,
        "area_pixels": 2,
        "mask_path": None,
        "mask_content_sha256": None,
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
                {
                    "id": "polyp-1",
                    "label_class_id": "swiftia",
                    "x_min": 5,
                    "y_min": 6,
                    "x_max": 10,
                    "y_max": 12,
                }
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


def _saved_raster_snapshot() -> tuple[DatasetVersion, DatasetVersionItem]:
    """Use the 0007 producer's managed raster-path and content-digest fields."""
    version, item = _saved_snapshot("0007", with_mask=True)
    mask = deepcopy(item.mask_annotation_snapshot_json[0])
    mask.update(
        geometry_kind="raster_mask",
        mask_path="projects/example/masks/swiftia.png",
        mask_content_sha256="b" * 64,
        polygon_json=None,
        x_min=2,
        y_min=3,
        x_max=6,
        y_max=7,
        area_pixels=12,
    )
    item.mask_annotation_snapshot_json = [mask]
    payload = _item_payload(item, schema_version="0007")
    item.snapshot_sha256 = canonical_json_sha256(payload)
    manifest = deepcopy(version.manifest_json)
    manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)
    return version, item


def test_original_0007_raster_snapshot_retains_traced_content() -> None:
    version, item = _saved_raster_snapshot()
    validate_frozen_dataset_manifest(version, [item])


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_path",
        "blank_path",
        "missing_digest",
        "short_digest",
        "uppercase_digest",
        "outside_bbox",
        "zero_area",
        "oversized_area",
    ],
)
def test_resigned_raster_metadata_cannot_create_untraceable_observations(tamper: str) -> None:
    version, item = _saved_raster_snapshot()
    mask = deepcopy(item.mask_annotation_snapshot_json[0])
    if tamper == "missing_path":
        mask.pop("mask_path")
    elif tamper == "blank_path":
        mask["mask_path"] = "   "
    elif tamper == "missing_digest":
        mask["mask_content_sha256"] = None
    elif tamper == "short_digest":
        mask["mask_content_sha256"] = "a" * 63
    elif tamper == "uppercase_digest":
        mask["mask_content_sha256"] = "A" * 64
    elif tamper == "outside_bbox":
        mask["x_max"] = item.width_px + 1
    elif tamper == "zero_area":
        mask["area_pixels"] = 0
    else:
        mask["area_pixels"] = item.width_px * item.height_px + 1
    item.mask_annotation_snapshot_json = [mask]

    # Even an internally rehashed item and manifest cannot supply missing
    # raster provenance or physically impossible source-pixel measurements.
    payload = _item_payload(item, schema_version="0007")
    item.snapshot_sha256 = canonical_json_sha256(payload)
    manifest = deepcopy(version.manifest_json)
    manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)
    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
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
        item.mask_annotation_snapshot_json[0]["polygon_json"][0][0] = 71
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


@pytest.mark.parametrize(
    "tamper",
    [
        "draft_status",
        "rejected_status",
        "missing_status",
        "empty_class",
        "unsupported_geometry",
        "missing_geometry",
        "nonstr_geometry",
    ],
)
def test_fully_resigned_mask_must_remain_verified_and_supported(tamper: str) -> None:
    """A recomputed digest cannot promote draft masks into verified QC evidence."""
    version, item = _saved_snapshot("0007", with_mask=True)
    snapshots = deepcopy(item.mask_annotation_snapshot_json)
    mask = snapshots[0]
    if tamper == "draft_status":
        mask["status"] = "draft"
    elif tamper == "rejected_status":
        mask["status"] = "rejected"
    elif tamper == "missing_status":
        mask.pop("status")
    elif tamper == "empty_class":
        mask["label_class_id"] = ""
        item.per_mask_class_counts_json = {"": 1}
    elif tamper == "unsupported_geometry":
        mask["geometry_kind"] = "unknown"
    elif tamper == "missing_geometry":
        mask.pop("geometry_kind")
    else:
        mask["geometry_kind"] = {"invalid": True}
    item.mask_annotation_snapshot_json = snapshots

    payload = _item_payload(item, schema_version="0007")
    item.snapshot_sha256 = canonical_json_sha256(payload)
    manifest = deepcopy(version.manifest_json)
    manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
    version.manifest_json = manifest
    version.manifest_sha256 = canonical_json_sha256(manifest)

    with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
        validate_frozen_dataset_manifest(version, [item])
