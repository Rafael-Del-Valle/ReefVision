"""Immutable segmentation dataset export helpers."""

from __future__ import annotations

import json
import shutil
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PIL import Image, ImageDraw, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import (
    EXPORT_SPLIT_DIRECTORIES,
    canonical_json_bytes,
    canonical_json_sha256,
    safe_export_filename,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.raster_edits import polygon_from_binary_region

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


def _write_data_yaml(
    output_root: Path,
    class_map: list[dict[str, Any]],
) -> None:
    yaml_lines = [
        "train: images/train",
        "val: images/validation",
        "test: images/test",
        "names:",
    ]
    for item in sorted(
        class_map,
        key=lambda value: int(value["class_index"]),
    ):
        yaml_lines.append(f"  {int(item['class_index'])}: {item['name']!s}")
    (output_root / "data.yaml").write_text(
        "\n".join(yaml_lines) + "\n",
        encoding="utf-8",
    )


def _normalized_polygon(
    snapshot: dict[str, Any],
    *,
    width: int,
    height: int,
) -> list[tuple[float, float]] | None:
    raw_points = snapshot.get("polygon_json")
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        return None
    points: list[tuple[float, float]] = []
    for raw in raw_points:
        if not isinstance(raw, list) or len(raw) != 2:
            return None
        x = min(max(float(raw[0]) / width, 0.0), 1.0)
        y = min(max(float(raw[1]) / height, 0.0), 1.0)
        points.append((x, y))
    if len(points) > 3 and points[0] == points[-1]:
        points = points[:-1]
    return points if len(set(points)) >= 3 else None


def write_yolo_segmentation_export(
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
    """Write Ultralytics polygon labels without changing detection export."""

    output_root = resolve_managed_project_path(settings, output_path)
    output_root.mkdir(parents=True, exist_ok=False)
    images_root = output_root / "images"
    labels_root = output_root / "labels"
    for directory in EXPORT_SPLIT_DIRECTORIES.values():
        (images_root / directory).mkdir(parents=True, exist_ok=True)
        (labels_root / directory).mkdir(parents=True, exist_ok=True)

    split_counts = {split: 0 for split in EXPORT_SPLIT_DIRECTORIES}
    polygon_count = 0
    vectorized_raster_count = 0
    skipped_raster_count = 0
    manifest_items: list[dict[str, Any]] = []
    ordered_items = sorted(
        items,
        key=lambda item: (
            item.split,
            item.group_key or "",
            item.original_filename.casefold(),
            item.image_id,
        ),
    )
    for item in ordered_items:
        split_directory = EXPORT_SPLIT_DIRECTORIES[item.split]
        target_filename = safe_export_filename(
            item.image_id,
            item.original_filename,
        )
        target_image = images_root / split_directory / target_filename
        shutil.copy2(image_paths[item.image_id], target_image)
        label_path = (labels_root / split_directory / Path(target_filename).stem).with_suffix(
            ".txt"
        )
        lines: list[str] = []
        item_polygon_count = 0
        item_skipped_rasters = 0
        item_vectorized_rasters = 0
        for snapshot in item.mask_annotation_snapshot_json:
            geometry_kind = snapshot.get("geometry_kind")
            if geometry_kind == "polygon":
                points = _normalized_polygon(
                    snapshot,
                    width=item.width_px,
                    height=item.height_px,
                )
                if points is None:
                    raise ValidationError(
                        f"Dataset item {item.image_id} contains an invalid polygon snapshot"
                    )
            elif geometry_kind == "raster_mask":
                raster = _verified_raster_mask(
                    settings,
                    snapshot,
                    expected_size=(item.width_px, item.height_px),
                )
                try:
                    raw_points = polygon_from_binary_region(raster)
                except ValidationError:
                    item_skipped_rasters += 1
                    continue
                points = [
                    (
                        min(max(float(x) / item.width_px, 0.0), 1.0),
                        min(max(float(y) / item.height_px, 0.0), 1.0),
                    )
                    for x, y in raw_points
                ]
                if len(set(points)) < 3:
                    item_skipped_rasters += 1
                    continue
                item_vectorized_rasters += 1
            else:
                item_skipped_rasters += 1
                continue

            coordinates = " ".join(
                coordinate for x, y in points for coordinate in (f"{x:.8f}", f"{y:.8f}")
            )
            lines.append(f"{int(snapshot['class_index'])} {coordinates}")
            item_polygon_count += 1
        label_path.write_text("\n".join(lines), encoding="utf-8")
        polygon_count += item_polygon_count
        vectorized_raster_count += item_vectorized_rasters
        skipped_raster_count += item_skipped_rasters
        split_counts[item.split] += 1
        manifest_items.append(
            {
                "image_id": item.image_id,
                "split": item.split,
                "image_sha256": item.image_sha256,
                "snapshot_sha256": item.snapshot_sha256,
                "polygon_count": item_polygon_count,
                "vectorized_raster_count": item_vectorized_rasters,
                "skipped_raster_count": item_skipped_rasters,
                "image_path": target_image.relative_to(output_root).as_posix(),
                "label_path": label_path.relative_to(output_root).as_posix(),
            }
        )

    _write_data_yaml(output_root, version.class_map_json)
    (output_root / "dataset-version-manifest.json").write_bytes(
        canonical_json_bytes(version.manifest_json)
    )
    export_manifest = {
        "export_id": export_id,
        "dataset_version_id": version.id,
        "dataset_version_number": version.version_number,
        "dataset_version_manifest_sha256": version.manifest_sha256,
        "format": "yolo_segmentation",
        "split_counts": split_counts,
        "polygon_count": polygon_count,
        "vectorized_raster_count": vectorized_raster_count,
        "skipped_raster_count": skipped_raster_count,
        "class_map": version.class_map_json,
        "items": manifest_items,
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
        "polygon_count": polygon_count,
        "vectorized_raster_count": vectorized_raster_count,
        "skipped_raster_count": skipped_raster_count,
        "archive_size_bytes": archive_file.stat().st_size,
    }


def _hex_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.lstrip("#")
    if len(normalized) != 6:
        return (255, 255, 255)
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def _semantic_palette(class_map: list[dict[str, Any]]) -> list[int]:
    palette = [0] * 768
    for item in class_map:
        pixel_value = int(item["class_index"]) + 1
        if pixel_value > 255:
            raise ValidationError("Semantic PNG export supports at most 255 classes")
        red, green, blue = _hex_rgb(str(item.get("display_color", "#ffffff")))
        offset = pixel_value * 3
        palette[offset : offset + 3] = [red, green, blue]
    return palette


def _verified_raster_mask(
    settings: Settings,
    snapshot: dict[str, Any],
    *,
    expected_size: tuple[int, int],
) -> Image.Image:
    mask_path = snapshot.get("mask_path")
    expected_sha256 = snapshot.get("mask_content_sha256")
    if not isinstance(mask_path, str) or not isinstance(expected_sha256, str):
        raise ValidationError("Raster snapshot is missing its managed path or checksum")
    path = resolve_managed_project_path(settings, mask_path)
    if not path.is_file() or _file_sha256(path) != expected_sha256:
        raise ValidationError("Raster mask content no longer matches the dataset snapshot")
    try:
        with Image.open(path) as image:
            image.load()
            if image.size != expected_size:
                raise ValidationError("Raster mask dimensions do not match the source image")
            return cast(
                Image.Image,
                image.convert("L").point(lambda value: 255 if value > 0 else 0),
            )
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Raster mask content could not be read") from exc


def write_semantic_mask_export(
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
    """Write indexed PNG masks; background is 0 and classes are index + 1."""

    output_root = resolve_managed_project_path(settings, output_path)
    output_root.mkdir(parents=True, exist_ok=False)
    images_root = output_root / "images"
    masks_root = output_root / "masks"
    for directory in EXPORT_SPLIT_DIRECTORIES.values():
        (images_root / directory).mkdir(parents=True, exist_ok=True)
        (masks_root / directory).mkdir(parents=True, exist_ok=True)

    palette = _semantic_palette(version.class_map_json)
    split_counts = {split: 0 for split in EXPORT_SPLIT_DIRECTORIES}
    manifest_items: list[dict[str, Any]] = []
    ordered_items = sorted(
        items,
        key=lambda item: (
            item.split,
            item.group_key or "",
            item.original_filename.casefold(),
            item.image_id,
        ),
    )
    for item in ordered_items:
        split_directory = EXPORT_SPLIT_DIRECTORIES[item.split]
        target_filename = safe_export_filename(
            item.image_id,
            item.original_filename,
        )
        target_image = images_root / split_directory / target_filename
        shutil.copy2(image_paths[item.image_id], target_image)
        semantic = Image.new("P", (item.width_px, item.height_px), 0)
        semantic.putpalette(palette)
        draw = ImageDraw.Draw(semantic)
        ordered_masks = sorted(
            item.mask_annotation_snapshot_json,
            key=lambda snapshot: (
                int(snapshot["class_index"]),
                str(snapshot["id"]),
            ),
        )
        for snapshot in ordered_masks:
            pixel_value = int(snapshot["class_index"]) + 1
            if snapshot.get("geometry_kind") == "polygon":
                raw_points = snapshot.get("polygon_json")
                if not isinstance(raw_points, list) or len(raw_points) < 3:
                    raise ValidationError("Semantic export encountered an invalid polygon")
                draw.polygon(
                    [(float(point[0]), float(point[1])) for point in raw_points],
                    fill=pixel_value,
                )
            elif snapshot.get("geometry_kind") == "raster_mask":
                raster = _verified_raster_mask(
                    settings,
                    snapshot,
                    expected_size=(item.width_px, item.height_px),
                )
                semantic.paste(pixel_value, mask=raster)
            else:
                raise ValidationError("Semantic export encountered unsupported mask geometry")
        target_mask = (masks_root / split_directory / Path(target_filename).stem).with_suffix(
            ".png"
        )
        semantic.save(target_mask, format="PNG", optimize=True)
        split_counts[item.split] += 1
        manifest_items.append(
            {
                "image_id": item.image_id,
                "split": item.split,
                "image_sha256": item.image_sha256,
                "snapshot_sha256": item.snapshot_sha256,
                "mask_annotation_count": item.mask_annotation_count,
                "image_path": target_image.relative_to(output_root).as_posix(),
                "mask_path": target_mask.relative_to(output_root).as_posix(),
            }
        )

    classes = {
        "background_pixel_value": 0,
        "classes": [
            {
                **item,
                "pixel_value": int(item["class_index"]) + 1,
            }
            for item in sorted(
                version.class_map_json,
                key=lambda value: int(value["class_index"]),
            )
        ],
        "overlap_policy": ("higher class index, then later mask id, overwrites earlier pixels"),
    }
    (output_root / "classes.json").write_text(
        json.dumps(classes, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_root / "dataset-version-manifest.json").write_bytes(
        canonical_json_bytes(version.manifest_json)
    )
    export_manifest = {
        "export_id": export_id,
        "dataset_version_id": version.id,
        "dataset_version_number": version.version_number,
        "dataset_version_manifest_sha256": version.manifest_sha256,
        "format": "semantic_masks",
        "split_counts": split_counts,
        "class_map": version.class_map_json,
        "items": manifest_items,
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
        "archive_size_bytes": archive_file.stat().st_size,
    }
