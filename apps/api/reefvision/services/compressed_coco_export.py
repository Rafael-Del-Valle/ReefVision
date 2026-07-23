"""Atomically convert ReefVision COCO raster masks to compact RLE strings."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.schemas.interchange import InterchangeExportResponse
from reefvision.services.coco_rle import encode_compact_counts
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_coco_export(
    settings: Settings,
    response: InterchangeExportResponse,
) -> InterchangeExportResponse:
    """Rewrite uncompressed raster segmentations and rebuild the portable ZIP."""

    if response.format not in {"coco_instance", "roboflow_coco"}:
        raise ValidationError("Compact COCO RLE is unavailable for this export format")
    manifest_path = resolve_managed_project_path(settings, response.manifest_path)
    root = manifest_path.parent
    annotations_path = root / (
        "roboflow-coco.json" if response.format == "roboflow_coco" else "annotations.json"
    )
    archive_path = resolve_managed_project_path(settings, response.archive_path)
    if not annotations_path.is_file() or not manifest_path.is_file():
        raise ValidationError("The generated COCO export is incomplete")

    document = json.loads(annotations_path.read_text(encoding="utf-8"))
    annotations = document.get("annotations")
    if not isinstance(annotations, list):
        raise ValidationError("The generated COCO export has no annotation list")
    converted = 0
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        segmentation = annotation.get("segmentation")
        if not isinstance(segmentation, dict):
            continue
        counts = segmentation.get("counts")
        size = segmentation.get("size")
        if not isinstance(counts, list):
            continue
        if not isinstance(size, list) or len(size) != 2:
            raise ValidationError("A generated COCO RLE mask is missing its size")
        normalized = [int(value) for value in counts]
        if any(value < 0 for value in normalized):
            raise ValidationError("A generated COCO RLE mask has negative run lengths")
        if sum(normalized) != int(size[0]) * int(size[1]):
            raise ValidationError("A generated COCO RLE mask does not cover its image")
        segmentation["counts"] = encode_compact_counts(normalized)
        annotation["iscrowd"] = 1
        converted += 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["coco_rle_encoding"] = "compressed"
    manifest["compressed_rle_mask_count"] = converted
    annotations_bytes = canonical_json_bytes(document)
    manifest_bytes = canonical_json_bytes(manifest)
    temporary_annotations = annotations_path.with_name(
        f".{annotations_path.name}.{uuid4().hex[:8]}.tmp"
    )
    temporary_manifest = manifest_path.with_name(
        f".{manifest_path.name}.{uuid4().hex[:8]}.tmp"
    )
    temporary_archive = archive_path.with_name(
        f".{archive_path.name}.{uuid4().hex[:8]}.tmp"
    )
    try:
        temporary_annotations.write_bytes(annotations_bytes)
        temporary_manifest.write_bytes(manifest_bytes)
        temporary_annotations.replace(annotations_path)
        temporary_manifest.replace(manifest_path)
        with zipfile.ZipFile(
            temporary_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file() and path not in {archive_path, temporary_archive}:
                    archive.write(path, path.relative_to(root).as_posix())
        temporary_archive.replace(archive_path)
    finally:
        temporary_annotations.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        temporary_archive.unlink(missing_ok=True)

    return response.model_copy(
        update={
            "archive_sha256": _file_sha256(archive_path),
            "archive_size_bytes": archive_path.stat().st_size,
            "warnings": [
                *response.warnings,
                f"Encoded {converted} raster masks with compact COCO RLE.",
            ],
        }
    )
