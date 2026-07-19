"""COCO detection and instance-segmentation export helpers."""

from __future__ import annotations

import shutil
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PIL import Image, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import (
    EXPORT_SPLIT_DIRECTORIES,
    canonical_json_bytes,
    canonical_json_sha256,
    safe_export_filename,
)
from reefvision.storage.projects import resolve_managed_project_path

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion
    from reefvision.db.models.dataset_version_item import DatasetVersionItem


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_export(output_root: Path, archive_file: Path) -> None:
    with zipfile.ZipFile(
        archive_file,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(output_root.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    arcname=path.relative_to(output_root).as_posix(),
                )


def _polygon_points(snapshot: dict[str, Any]) -> list[tuple[float, float]]:
    raw_points = snapshot.get("polygon_json")
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        raise ValidationError("COCO export encountered an invalid polygon snapshot")
    points: list[tuple[float, float]] = []
    for raw_point in raw_points:
        if not isinstance(raw_point, list) or len(raw_point) != 2:
            raise ValidationError("COCO export encountered an invalid polygon point")
        points.append((float(raw_point[0]), float(raw_point[1])))
    if len(points) > 3 and points[0] == points[-1]:
        points = points[:-1]
    if len(set(points)) < 3:
        raise ValidationError("COCO polygons require at least three unique points")
    return points


def _polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(
                points,
                points[1:] + points[:1],
                strict=True,
            )
        )
        / 2.0
    )


def _polygon_bbox(points: list[tuple[float, float]]) -> list[float]:
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    x_min = min(x_values)
    y_min = min(y_values)
    return [
        x_min,
        y_min,
        max(x_values) - x_min,
        max(y_values) - y_min,
    ]


def _verified_raster_mask(
    settings: Settings,
    snapshot: dict[str, Any],
    *,
    expected_size: tuple[int, int],
) -> Image.Image:
    mask_path = snapshot.get("mask_path")
    expected_sha256 = snapshot.get("mask_content_sha256")
    if not isinstance(mask_path, str) or not isinstance(expected_sha256, str):
        raise ValidationError(
            "Raster snapshot is missing its managed path or checksum"
        )
    path = resolve_managed_project_path(settings, mask_path)
    if not path.is_file() or _file_sha256(path) != expected_sha256:
        raise ValidationError(
            "Raster mask content no longer matches the immutable dataset snapshot"
        )
    try:
        with Image.open(path) as image:
            image.load()
            if image.size != expected_size:
                raise ValidationError(
                    "Raster mask dimensions do not match the source image"
                )
            return cast(
                Image.Image,
                image.convert("L").point(lambda value: 255 if value > 0 else 0),
            )
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Raster mask content could not be read") from exc


def _uncompressed_coco_rle(mask: Image.Image) -> dict[str, Any]:
    width, height = mask.size
    pixels = mask.load()
    counts: list[int] = []
    current_value = 0
    current_count = 0
    area = 0
    for x in range(width):
        for y in range(height):
            value = 1 if int(pixels[x, y]) > 0 else 0
            area += value
            if value == current_value:
                current_count += 1
            else:
                counts.append(current_count)
                current_count = 1
                current_value = value
    counts.append(current_count)
    return {
        "size": [height, width],
        "counts": counts,
        "area": area,
    }


def _box_annotation(
    snapshot: dict[str, Any],
    *,
    annotation_id: int,
    image_id: int,
) -> dict[str, Any]:
    x_min = float(snapshot["x_min"])
    y_min = float(snapshot["y_min"])
    width = float(snapshot["x_max"]) - x_min
    height = float(snapshot["y_max"]) - y_min
    if width <= 0 or height <= 0:
        raise ValidationError("COCO export encountered a non-positive bounding box")
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": int(snapshot["class_index"]) + 1,
        "bbox": [x_min, y_min, width, height],
        "area": width * height,
        "segmentation": [],
        "iscrowd": 0,
        "reefvision_annotation_id": str(snapshot["id"]),
        "reefvision_geometry_kind": "bounding_box",
    }


def _mask_annotation(
    settings: Settings,
    snapshot: dict[str, Any],
    *,
    annotation_id: int,
    image_id: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    geometry_kind = str(snapshot.get("geometry_kind"))
    if geometry_kind == "polygon":
        points = _polygon_points(snapshot)
        segmentation: Any = [
            [coordinate for point in points for coordinate in point]
        ]
        bbox = _polygon_bbox(points)
        area = _polygon_area(points)
    elif geometry_kind == "raster_mask":
        raster = _verified_raster_mask(
            settings,
            snapshot,
            expected_size=(width, height),
        )
        bounds = raster.getbbox()
        if bounds is None:
            raise ValidationError("COCO export encountered an empty raster mask")
        left, top, right, bottom = bounds
        rle = _uncompressed_coco_rle(raster)
        segmentation = {"size": rle["size"], "counts": rle["counts"]}
        bbox = [
            float(left),
            float(top),
            float(right - left),
            float(bottom - top),
        ]
        area = float(rle["area"])
    else:
        raise ValidationError(
            f"COCO export does not support mask geometry {geometry_kind!r}"
        )
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": int(snapshot["class_index"]) + 1,
        "bbox": bbox,
        "area": area,
        "segmentation": segmentation,
        "iscrowd": 0,
        "reefvision_annotation_id": str(snapshot["id"]),
        "reefvision_geometry_kind": geometry_kind,
    }


def write_coco_instances_export(
    settings: Settings,
    *,
    export_id: str,
    version: DatasetVersion,
    items: list[DatasetVersionItem],
    image_paths: dict[str, Path],
    output_path: str,
    manifest_path: str,
    archive_path: str,
) -> dict[str, Any]:
    """Write one COCO instance JSON file per immutable dataset split."""

    output_root = resolve_managed_project_path(settings, output_path)
    output_root.mkdir(parents=True, exist_ok=False)
    images_root = output_root / "images"
    annotations_root = output_root / "annotations"
    annotations_root.mkdir(parents=True, exist_ok=True)
    for directory in EXPORT_SPLIT_DIRECTORIES.values():
        (images_root / directory).mkdir(parents=True, exist_ok=True)

    categories = [
        {
            "id": int(item["class_index"]) + 1,
            "name": str(item["name"]),
            "supercategory": str(item.get("scientific_name") or "reefvision"),
            "reefvision_label_class_id": str(item["id"]),
            "reefvision_state_name": item.get("state_name"),
            "reefvision_display_color": item.get("display_color"),
        }
        for item in sorted(
            version.class_map_json,
            key=lambda value: int(value["class_index"]),
        )
    ]
    split_payloads: dict[str, dict[str, Any]] = {
        split: {
            "info": {
                "description": f"ReefVision dataset version {version.version_number}",
                "version": str(version.version_number),
                "reefvision_dataset_version_id": version.id,
                "reefvision_manifest_sha256": version.manifest_sha256,
            },
            "licenses": [],
            "images": [],
            "annotations": [],
            "categories": categories,
        }
        for split in EXPORT_SPLIT_DIRECTORIES
    }
    split_image_ids: dict[str, int] = dict.fromkeys(EXPORT_SPLIT_DIRECTORIES, 0)
    split_annotation_ids: dict[str, int] = dict.fromkeys(EXPORT_SPLIT_DIRECTORIES, 0)
    split_counts = dict.fromkeys(EXPORT_SPLIT_DIRECTORIES, 0)
    box_count = 0
    mask_count = 0
    manifest_items: list[dict[str, Any]] = []

    for item in sorted(
        items,
        key=lambda value: (
            value.split,
            value.group_key or "",
            value.original_filename.casefold(),
            value.image_id,
        ),
    ):
        split = item.split
        split_directory = EXPORT_SPLIT_DIRECTORIES[split]
        split_image_ids[split] += 1
        coco_image_id = split_image_ids[split]
        target_filename = safe_export_filename(
            item.image_id,
            item.original_filename,
        )
        target_image = images_root / split_directory / target_filename
        shutil.copy2(image_paths[item.image_id], target_image)
        split_payloads[split]["images"].append(
            {
                "id": coco_image_id,
                "file_name": target_image.relative_to(output_root).as_posix(),
                "width": item.width_px,
                "height": item.height_px,
                "reefvision_image_id": item.image_id,
                "reefvision_image_sha256": item.image_sha256,
                "reefvision_group_key": item.group_key,
                "reefvision_snapshot_sha256": item.snapshot_sha256,
            }
        )
        item_box_count = 0
        item_mask_count = 0
        for snapshot in item.annotation_snapshot_json:
            split_annotation_ids[split] += 1
            split_payloads[split]["annotations"].append(
                _box_annotation(
                    snapshot,
                    annotation_id=split_annotation_ids[split],
                    image_id=coco_image_id,
                )
            )
            item_box_count += 1
        for snapshot in item.mask_annotation_snapshot_json:
            split_annotation_ids[split] += 1
            split_payloads[split]["annotations"].append(
                _mask_annotation(
                    settings,
                    snapshot,
                    annotation_id=split_annotation_ids[split],
                    image_id=coco_image_id,
                    width=item.width_px,
                    height=item.height_px,
                )
            )
            item_mask_count += 1
        split_counts[split] += 1
        box_count += item_box_count
        mask_count += item_mask_count
        manifest_items.append(
            {
                "image_id": item.image_id,
                "split": split,
                "image_sha256": item.image_sha256,
                "snapshot_sha256": item.snapshot_sha256,
                "box_annotation_count": item_box_count,
                "mask_annotation_count": item_mask_count,
                "image_path": target_image.relative_to(output_root).as_posix(),
            }
        )

    annotation_files: dict[str, str] = {}
    for split, payload in split_payloads.items():
        annotation_path = annotations_root / f"instances_{split}.json"
        annotation_path.write_bytes(canonical_json_bytes(payload))
        annotation_files[split] = annotation_path.relative_to(output_root).as_posix()
    (output_root / "dataset-version-manifest.json").write_bytes(
        canonical_json_bytes(version.manifest_json)
    )
    export_manifest = {
        "export_id": export_id,
        "dataset_version_id": version.id,
        "dataset_version_number": version.version_number,
        "dataset_version_manifest_sha256": version.manifest_sha256,
        "format": "coco_instances",
        "split_counts": split_counts,
        "box_annotation_count": box_count,
        "mask_annotation_count": mask_count,
        "class_map": version.class_map_json,
        "annotation_files": annotation_files,
        "items": manifest_items,
        "raster_encoding": "COCO uncompressed column-major RLE",
    }
    resolve_managed_project_path(settings, manifest_path).write_bytes(
        canonical_json_bytes(export_manifest)
    )
    archive_file = resolve_managed_project_path(settings, archive_path)
    _archive_export(output_root, archive_file)
    return {
        "manifest_sha256": canonical_json_sha256(export_manifest),
        "split_counts": split_counts,
        "item_count": len(manifest_items),
        "box_annotation_count": box_count,
        "mask_annotation_count": mask_count,
        "archive_size_bytes": archive_file.stat().st_size,
    }
