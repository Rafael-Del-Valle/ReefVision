"""Validate immutable image-level evidence before standalone or saved frozen QC.

A saved Workflow Builder reference and aggregate count can both remain valid
after original biological annotations were altered in a dataset-version row.
The separately persisted manifest provides the original per-image content and
SHA-256 without consulting mutable live annotations.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from math import isfinite
from typing import Any, cast

from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256

# The API currently writes mask/measurement-aware 0007 manifests, including
# when there are no masks. Historical detection-only 0006 snapshots also exist.
SUPPORTED_SNAPSHOT_SCHEMAS = frozenset({"0006", "0007"})


def _valid_detection_box(snapshot: dict[str, Any], width_px: Any, height_px: Any) -> bool:
    """Apply the original editor's source-pixel box bounds to frozen evidence."""
    if type(width_px) is not int or type(height_px) is not int or width_px <= 0 or height_px <= 0:
        return False
    coordinates = [snapshot.get(key) for key in ("x_min", "y_min", "x_max", "y_max")]
    if any(type(value) not in (int, float) for value in coordinates):
        return False
    x_min, y_min, x_max, y_max = cast(tuple[float, float, float, float], tuple(coordinates))
    width, height = width_px, height_px
    try:
        if not all(isfinite(value) for value in (x_min, y_min, x_max, y_max)):
            return False
    except OverflowError:
        return False
    return 0 <= x_min < x_max <= width and 0 <= y_min < y_max <= height


def _valid_frozen_polygon(snapshot: dict[str, Any], width_px: Any, height_px: Any) -> bool:
    """Check a frozen polygon against the source-pixel editor's saved geometry."""
    if not _valid_detection_box(snapshot, width_px, height_px):
        return False
    raw_points = snapshot.get("polygon_json")
    area_pixels = snapshot.get("area_pixels")
    if (
        not isinstance(raw_points, list)
        or len(raw_points) < 3
        or type(area_pixels) is not int
        or area_pixels < 1
    ):
        return False

    points: list[tuple[float, float]] = []
    for raw_point in raw_points:
        if (
            not isinstance(raw_point, list)
            or len(raw_point) != 2
            or any(type(value) not in (int, float) for value in raw_point)
        ):
            return False
        try:
            x, y = float(raw_point[0]), float(raw_point[1])
        except (OverflowError, ValueError):
            return False
        if not (isfinite(x) and isfinite(y) and 0 <= x <= width_px and 0 <= y <= height_px):
            return False
        points.append((x, y))

    if len(set(points)) < 3 or any(
        points[index] == points[(index + 1) % len(points)] for index in range(len(points))
    ):
        return False
    if (
        min(point[0] for point in points) != snapshot["x_min"]
        or min(point[1] for point in points) != snapshot["y_min"]
        or max(point[0] for point in points) != snapshot["x_max"]
        or max(point[1] for point in points) != snapshot["y_max"]
    ):
        return False
    area = (
        abs(
            sum(
                x * points[(index + 1) % len(points)][1] - points[(index + 1) % len(points)][0] * y
                for index, (x, y) in enumerate(points)
            )
        )
        / 2.0
    )
    return isfinite(area) and area >= 1.0 and area_pixels == max(1, round(area))


def _valid_frozen_raster_mask(snapshot: dict[str, Any], width_px: Any, height_px: Any) -> bool:
    """Require traceable source-pixel raster evidence without opening user assets.

    A recorded SHA-256 is a provenance claim, not proof the file still exists
    or that its bytes have not changed since snapshot creation.
    """
    if not _valid_detection_box(snapshot, width_px, height_px):
        return False
    path = snapshot.get("mask_path")
    digest = snapshot.get("mask_content_sha256")
    area = snapshot.get("area_pixels")
    return (
        type(path) is str
        and bool(path.strip())
        and type(digest) is str
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and type(area) is int
        and 0 < area <= width_px * height_px
    )

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
    seen_annotation_ids: set[str] = set()
    seen_mask_annotation_ids: set[str] = set()
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
                    or not snapshot["label_class_id"]
                    or snapshot.get("status") != "verified"
                    or type(snapshot.get("geometry_kind")) is not str
                    or snapshot["geometry_kind"] not in {"polygon", "raster_mask"}
                    or (
                        snapshot["geometry_kind"] == "polygon"
                        and not _valid_frozen_polygon(snapshot, item.width_px, item.height_px)
                    )
                    or (
                        snapshot["geometry_kind"] == "raster_mask"
                        and not _valid_frozen_raster_mask(snapshot, item.width_px, item.height_px)
                    )
                    for snapshot in mask_snapshots
                )
                or item.per_mask_class_counts_json
                != dict(Counter(snapshot["label_class_id"] for snapshot in mask_snapshots))
            ):
                raise ValidationError(message)
            # Only verified original masks of supported producer geometries
            # can contribute biological observations to a frozen study.
            # Rehashing a draft or unsupported geometry does not authorize QC.
            # Mask annotations have their own globally unique database IDs.
            # A duplicated/empty ID can inflate a segmentation census even
            # when both nested SHA-256 digests and taxonomic totals are rehashed.
            for snapshot in mask_snapshots:
                mask_id = snapshot.get("id")
                if type(mask_id) is not str or not mask_id or mask_id in seen_mask_annotation_ids:
                    raise ValidationError(message)
                seen_mask_annotation_ids.add(mask_id)

        # Even a locally recomputed item and manifest digest cannot make an
        # internally inconsistent biological count valid. Verify the frozen
        # annotation census independently of both stored count fields.
        annotations = item.annotation_snapshot_json
        if (
            type(item.annotation_count) is not int
            or not isinstance(annotations, list)
            or item.annotation_count != len(annotations)
            or any(
                not isinstance(annotation, dict)
                or type(annotation.get("label_class_id")) is not str
                or not _valid_detection_box(annotation, item.width_px, item.height_px)
                for annotation in annotations
            )
            or item.per_class_counts_json
            != dict(Counter(annotation["label_class_id"] for annotation in annotations))
        ):
            raise ValidationError(message)

        # An annotation identity must refer to one biological observation,
        # even if a local actor recomputes all unkeyed SHA-256 checksums and
        # makes the totals and taxonomic census internally self-consistent.
        # Database annotation IDs are globally unique across project images.
        for annotation in annotations:
            annotation_id = annotation.get("id")
            if (
                type(annotation_id) is not str
                or not annotation_id
                or annotation_id in seen_annotation_ids
            ):
                raise ValidationError(message)
            seen_annotation_ids.add(annotation_id)

        payload = _item_payload(item, schema_version=schema_version)
        if canonical_json_sha256(payload) != item.snapshot_sha256 or entries.get(item.image_id) != {
            **payload,
            "snapshot_sha256": item.snapshot_sha256,
        }:
            raise ValidationError(message)
