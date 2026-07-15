"""Dataset-version manifest and export filesystem helpers."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reefvision.config import Settings
from reefvision.storage.projects import resolve_managed_project_path

if TYPE_CHECKING:
    from reefvision.db.models.dataset_version import DatasetVersion
    from reefvision.db.models.dataset_version_item import DatasetVersionItem


EXPORT_SPLIT_DIRECTORIES: dict[str, str] = {
    "train": "train",
    "validation": "validation",
    "test": "test",
    "unassigned": "unassigned",
}

YOLO_DATASET_KEYS: dict[str, str | None] = {
    "train": "train",
    "validation": "val",
    "test": "test",
    "unassigned": None,
}


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize JSON content deterministically for stable hashing."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def canonical_json_sha256(payload: Any) -> str:
    return sha256(canonical_json_bytes(payload)).hexdigest()


def dataset_export_relative_paths(
    *,
    project_storage_root: str,
    version_number: int,
    export_id: str,
) -> tuple[str, str, str]:
    relative_output = f"{project_storage_root}/exports/v{version_number:04d}-{export_id}"
    manifest_path = f"{relative_output}/export-manifest.json"
    archive_path = f"{relative_output}.zip"
    return relative_output, manifest_path, archive_path


def safe_export_filename(image_id: str, original_filename: str) -> str:
    base = Path(original_filename).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    if not sanitized:
        sanitized = "image"
    return f"{image_id[:8]}_{sanitized}"


def remove_export_artifacts(
    settings: Settings,
    *,
    output_path: str,
    archive_path: str | None = None,
) -> None:
    output_root = resolve_managed_project_path(settings, output_path)
    shutil.rmtree(output_root, ignore_errors=True)
    if archive_path is not None:
        resolve_managed_project_path(settings, archive_path).unlink(missing_ok=True)


def write_yolo_detection_export(
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
    output_root = resolve_managed_project_path(settings, output_path)
    output_root.mkdir(parents=True, exist_ok=False)
    images_root = output_root / "images"
    labels_root = output_root / "labels"

    class_map = sorted(
        version.class_map_json,
        key=lambda item: (int(item["class_index"]), str(item["name"]).casefold()),
    )
    names = {int(item["class_index"]): str(item["name"]) for item in class_map}
    split_counts: dict[str, int] = {split: 0 for split in EXPORT_SPLIT_DIRECTORIES}
    manifest_items: list[dict[str, Any]] = []

    for split_directory in EXPORT_SPLIT_DIRECTORIES.values():
        (images_root / split_directory).mkdir(parents=True, exist_ok=True)
        (labels_root / split_directory).mkdir(parents=True, exist_ok=True)

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
        target_filename = safe_export_filename(item.image_id, item.original_filename)
        source_path = image_paths[item.image_id]
        target_image = images_root / split_directory / target_filename
        shutil.copy2(source_path, target_image)
        label_path = (labels_root / split_directory / Path(target_filename).stem).with_suffix(
            ".txt"
        )
        yolo_lines: list[str] = []
        for annotation in item.annotation_snapshot_json:
            width = float(item.width_px)
            height = float(item.height_px)
            x_min = float(annotation["x_min"])
            y_min = float(annotation["y_min"])
            x_max = float(annotation["x_max"])
            y_max = float(annotation["y_max"])
            x_center = ((x_min + x_max) / 2.0) / width
            y_center = ((y_min + y_max) / 2.0) / height
            box_width = (x_max - x_min) / width
            box_height = (y_max - y_min) / height
            class_index = int(annotation["class_index"])
            yolo_lines.append(
                f"{class_index} {x_center:.8f} {y_center:.8f} {box_width:.8f} {box_height:.8f}"
            )
        label_path.write_text("\n".join(yolo_lines), encoding="utf-8")
        relative_image = target_image.relative_to(output_root).as_posix()
        relative_label = label_path.relative_to(output_root).as_posix()
        manifest_items.append(
            {
                "image_id": item.image_id,
                "original_filename": item.original_filename,
                "split": item.split,
                "group_key": item.group_key,
                "image_sha256": item.image_sha256,
                "annotation_count": item.annotation_count,
                "snapshot_sha256": item.snapshot_sha256,
                "image_path": relative_image,
                "label_path": relative_label,
            }
        )
        split_counts[item.split] += 1

    yaml_lines = [
        "path: .",
        "train: images/train",
        "val: images/validation",
        "test: images/test",
        "names:",
    ]
    for class_index, class_name in sorted(names.items()):
        yaml_lines.append(f"  {class_index}: {class_name}")
    (output_root / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    version_manifest_path = output_root / "dataset-version-manifest.json"
    version_manifest_path.write_bytes(canonical_json_bytes(version.manifest_json))

    export_manifest = {
        "export_id": export_id,
        "dataset_version_id": version.id,
        "dataset_version_number": version.version_number,
        "dataset_version_manifest_sha256": version.manifest_sha256,
        "format": "yolo_detection",
        "split_counts": split_counts,
        "class_map": class_map,
        "items": manifest_items,
    }
    export_manifest_file = resolve_managed_project_path(settings, manifest_path)
    export_manifest_file.write_bytes(canonical_json_bytes(export_manifest))

    archive_file = resolve_managed_project_path(settings, archive_path)
    with zipfile.ZipFile(archive_file, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(output_root).as_posix())

    return {
        "manifest_sha256": canonical_json_sha256(export_manifest),
        "split_counts": split_counts,
        "item_count": len(manifest_items),
        "archive_size_bytes": archive_file.stat().st_size,
    }
