"""Immutable crop-classification dataset exports."""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

CLASSIFICATION_MODES = ("multiclass", "binary_state")
CLASSIFICATION_SPLITS = ("train", "validation", "test")
CLASSIFICATION_SPLIT_DIRECTORIES = {
    "train": "train",
    "validation": "val",
    "test": "test",
}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return normalized or "class"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classification_class_key(
    class_record: dict[str, Any],
    *,
    mode: str,
) -> tuple[str, str] | None:
    if mode == "binary_state":
        state = str(class_record.get("state_name") or "").strip().casefold()
        if state not in {"open", "closed"}:
            return None
        return state, state
    class_index = int(class_record["class_index"])
    name = str(class_record["name"])
    return f"c{class_index:03d}_{_slug(name)}", name


def preview_classification_dataset(
    version: DatasetVersion,
    items: list[DatasetVersionItem],
    *,
    mode: str,
    minimum_crop_size_px: int,
) -> dict[str, Any]:
    if mode not in CLASSIFICATION_MODES:
        raise ValueError(f"Unsupported classification mode: {mode}")
    classes_by_id = {str(item["id"]): dict(item) for item in version.class_map_json}
    split_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    removed = 0
    missing_state = 0

    for item in items:
        if item.split not in CLASSIFICATION_SPLITS:
            continue
        for annotation in item.annotation_snapshot_json:
            width = float(annotation["x_max"]) - float(annotation["x_min"])
            height = float(annotation["y_max"]) - float(annotation["y_min"])
            if width < minimum_crop_size_px or height < minimum_crop_size_px:
                removed += 1
                continue
            class_record = classes_by_id.get(str(annotation["label_class_id"]))
            if class_record is None:
                continue
            resolved = classification_class_key(class_record, mode=mode)
            if resolved is None:
                missing_state += 1
                continue
            key, label = resolved
            labels[key] = label
            class_counts[key] += 1
            split_counts[item.split] += 1

    warnings: list[str] = []
    if removed:
        warnings.append(
            f"{removed} crop(s) smaller than {minimum_crop_size_px}×"
            f"{minimum_crop_size_px} pixels were removed during preprocessing."
        )
    if missing_state:
        warnings.append(
            f"{missing_state} crop(s) were excluded because their class lacks an open/closed state."
        )
    if split_counts.get("validation", 0) == 0:
        warnings.append("The validation split contains no eligible classification crops.")
    if len(class_counts) < 2:
        warnings.append("Classification training requires at least two eligible classes.")
    return {
        "dataset_version_id": version.id,
        "mode": mode,
        "minimum_crop_size_px": minimum_crop_size_px,
        "eligible_crop_count": sum(class_counts.values()),
        "removed_during_preprocessing_count": removed,
        "missing_state_count": missing_state,
        "split_counts": dict(split_counts),
        "classes": [
            {"key": key, "label": labels[key], "crop_count": count}
            for key, count in sorted(class_counts.items())
        ],
        "warnings": warnings,
    }


def write_classification_export(
    settings: Settings,
    *,
    export_id: str,
    version: DatasetVersion,
    items: list[DatasetVersionItem],
    image_paths: dict[str, Path],
    output_path: str,
    manifest_path: str,
    archive_path: str,
    mode: str,
    minimum_crop_size_px: int = 10,
    padding_fraction: float = 0.0,
) -> dict[str, Any]:
    preview = preview_classification_dataset(
        version,
        items,
        mode=mode,
        minimum_crop_size_px=minimum_crop_size_px,
    )
    output_root = resolve_managed_project_path(settings, output_path)
    output_root.mkdir(parents=True, exist_ok=False)
    classes_by_id = {str(item["id"]): dict(item) for item in version.class_map_json}
    manifest_items: list[dict[str, Any]] = []
    split_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    class_map: dict[str, dict[str, Any]] = {}

    for item in sorted(
        items,
        key=lambda row: (
            row.split,
            row.group_key or "",
            row.original_filename.casefold(),
            row.image_id,
        ),
    ):
        if item.split not in CLASSIFICATION_SPLITS:
            continue
        source_path = image_paths[item.image_id]
        with Image.open(source_path) as source:
            image = source.convert("RGB")
            for crop_index, annotation in enumerate(item.annotation_snapshot_json):
                x_min = float(annotation["x_min"])
                y_min = float(annotation["y_min"])
                x_max = float(annotation["x_max"])
                y_max = float(annotation["y_max"])
                box_width = x_max - x_min
                box_height = y_max - y_min
                if box_width < minimum_crop_size_px or box_height < minimum_crop_size_px:
                    continue
                class_record = classes_by_id.get(str(annotation["label_class_id"]))
                if class_record is None:
                    continue
                resolved = classification_class_key(class_record, mode=mode)
                if resolved is None:
                    continue
                class_key, class_label = resolved
                padding_x = box_width * padding_fraction
                padding_y = box_height * padding_fraction
                left = max(0, int(x_min - padding_x))
                top = max(0, int(y_min - padding_y))
                right = min(item.width_px, int(x_max + padding_x + 0.999999))
                bottom = min(item.height_px, int(y_max + padding_y + 0.999999))
                if right <= left or bottom <= top:
                    continue
                split_directory = CLASSIFICATION_SPLIT_DIRECTORIES[item.split]
                destination_root = output_root / split_directory / class_key
                destination_root.mkdir(parents=True, exist_ok=True)
                annotation_id = str(annotation.get("id") or f"crop-{crop_index}")
                crop_identity = f"{item.image_id}:{annotation_id}".encode("utf-8")
                filename = f"{sha256(crop_identity).hexdigest()[:24]}.jpg"
                destination = destination_root / filename
                image.crop((left, top, right, bottom)).save(
                    destination,
                    format="JPEG",
                    quality=95,
                    optimize=True,
                )
                class_map[class_key] = {
                    "label": class_label,
                    "label_class_id": (
                        str(class_record["id"]) if mode == "multiclass" else None
                    ),
                    "class_index": (
                        int(class_record["class_index"]) if mode == "multiclass" else None
                    ),
                    "scientific_name": class_record.get("scientific_name"),
                    "state_name": class_record.get("state_name"),
                }
                manifest_items.append(
                    {
                        "image_id": item.image_id,
                        "annotation_id": annotation_id,
                        "image_sha256": item.image_sha256,
                        "snapshot_sha256": item.snapshot_sha256,
                        "split": item.split,
                        "dataset_split_directory": split_directory,
                        "group_key": item.group_key,
                        "source_bbox": [x_min, y_min, x_max, y_max],
                        "crop_bbox": [left, top, right, bottom],
                        "class_key": class_key,
                        "class_label": class_label,
                        "source_label_class_id": str(class_record["id"]),
                        "crop_path": destination.relative_to(output_root).as_posix(),
                        "crop_sha256": _file_sha256(destination),
                    }
                )
                split_counts[item.split] += 1
                class_counts[class_key] += 1

    version_manifest = output_root / "dataset-version-manifest.json"
    version_manifest.write_bytes(canonical_json_bytes(version.manifest_json))
    export_manifest = {
        "export_id": export_id,
        "dataset_version_id": version.id,
        "dataset_version_number": version.version_number,
        "dataset_version_manifest_sha256": version.manifest_sha256,
        "format": "classification",
        "classification_mode": mode,
        "minimum_crop_size_px": minimum_crop_size_px,
        "padding_fraction": padding_fraction,
        "preprocessing_note": (
            f"Crops smaller than {minimum_crop_size_px}×{minimum_crop_size_px} pixels "
            "were removed during preprocessing."
        ),
        "split_directory_map": CLASSIFICATION_SPLIT_DIRECTORIES,
        "split_counts": dict(split_counts),
        "class_counts": dict(class_counts),
        "class_map": class_map,
        "preview": preview,
        "items": manifest_items,
    }
    manifest_file = resolve_managed_project_path(settings, manifest_path)
    manifest_file.write_bytes(canonical_json_bytes(export_manifest))
    archive_file = resolve_managed_project_path(settings, archive_path)
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_file, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(output_root).as_posix())

    return {
        "manifest_sha256": canonical_json_sha256(export_manifest),
        "classification_mode": mode,
        "split_counts": dict(split_counts),
        "class_counts": dict(class_counts),
        "item_count": len(manifest_items),
        "removed_during_preprocessing_count": preview[
            "removed_during_preprocessing_count"
        ],
        "archive_size_bytes": archive_file.stat().st_size,
    }
