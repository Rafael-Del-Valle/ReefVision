"""Strict external annotation adapters: COCO JSON and YOLO TXT/YAML.

Adapt supported formats into ReefVision's existing, provenance-aware CoralNet
import pipeline. Ambiguous image or class identity is reported, not guessed.
"""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from pathlib import PureWindowsPath
from typing import Any

from reefvision.domain.errors import ValidationError


def is_coco(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("images"), list)
        and isinstance(payload.get("annotations"), list)
        and isinstance(payload.get("categories"), list)
    )


def _image_name(value: object) -> str:
    value = str(value or "").replace("\\", "/")
    return value.rsplit("/", 1)[-1]


def convert_coco(
    payload: dict[str, Any],
    source_file: str,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    list[str],
    list[tuple[str, str, dict[str, Any]]],
]:
    categories: dict[int, str] = {}
    mappings: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    coco_masks: list[tuple[str, str, dict[str, Any]]] = []
    for raw in payload["categories"]:
        if not isinstance(raw, dict):
            raise ValidationError("COCO categories must be objects")
        try:
            cid = int(raw["id"])
            label = str(raw["name"]).strip()
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError("COCO category must contain an integer id and name") from exc
        if not label or len(label) > 200:
            raise ValidationError("COCO categories must have a nonempty name <=200 characters")
        if cid in categories and categories[cid] != label:
            raise ValidationError(f"Conflicting COCO category id {cid}")
        categories[cid] = label
        mappings[label] = {"id": f"coco:{source_file}:{cid}", "short_label_code": label, "long_label_code": label}

    images: dict[int, str] = {}
    for raw in payload["images"]:
        if not isinstance(raw, dict) or not raw.get("file_name"):
            raise ValidationError("COCO images need id and file_name")
        iid = int(raw["id"])
        name = str(raw["file_name"])
        if iid in images and images[iid] != name:
            raise ValidationError(f"Conflicting COCO image id {iid}")
        images[iid] = name

    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, raw in enumerate(payload["annotations"]):
        if not isinstance(raw, dict):
            warnings.append(f"COCO annotation #{index}: invalid record")
            continue
        image_name = images.get(int(raw.get("image_id", -1)))
        label = categories.get(int(raw.get("category_id", -1)))
        if image_name is None or label is None:
            warnings.append(f"COCO annotation #{index}: unknown image/category ID")
            continue
        record: dict[str, Any] = {
            "id": f"coco:{source_file}:{raw.get('id', index)}",
            "label_short_code": label,
            "label_long_code": label,
            "label_id": f"coco:{source_file}:{raw['category_id']}",
            "verified": False,
            "data": {"external_format": "coco", "external_category_id": raw["category_id"]},
        }
        segmentation = raw.get("segmentation")
        if isinstance(segmentation, dict):
            coco_masks.append((image_name, label, dict(raw)))
            continue
        if isinstance(segmentation, list) and segmentation:
            polygons: list[dict[str, Any]] = []
            for ring in segmentation:
                if not isinstance(ring, list) or len(ring) < 6 or len(ring) % 2:
                    warnings.append(f"COCO annotation #{index}: malformed polygon skipped")
                    polygons.clear()
                    break
                polygons.append({
                    "points": [[float(ring[i]), float(ring[i + 1])] for i in range(0, len(ring), 2)],
                    "holes": [],
                })
            if not polygons:
                continue
            if len(polygons) == 1:
                record.update(type="PolygonAnnotation", points=polygons[0]["points"], holes=[])
            else:
                record.update(type="MultiPolygonAnnotation", polygons=polygons)
        else:
            box = raw.get("bbox")
            if not isinstance(box, list) or len(box) != 4:
                warnings.append(f"COCO annotation #{index}: no supported polygon or box")
                continue
            try:
                x, y, width, height = (float(v) for v in box)
            except (ValueError, TypeError):
                warnings.append(f"COCO annotation #{index}: invalid bbox")
                continue
            if any(not isfinite(v) for v in (x, y, width, height)) or width <= 0 or height <= 0:
                warnings.append(f"COCO annotation #{index}: empty bbox")
                continue
            record.update(
                type="RectangleAnnotation",
                top_left=[x, y],
                bottom_right=[x + width, y + height],
            )
        output[image_name].append(record)
    return dict(output), mappings, warnings, coco_masks


def yolo_names(dataset: object) -> dict[int, str]:
    if not isinstance(dataset, dict):
        return {}
    raw = dataset.get("names")
    if isinstance(raw, list):
        return {i: str(name).strip() for i, name in enumerate(raw)}
    if isinstance(raw, dict):
        return {int(key): str(value).strip() for key, value in raw.items()}
    return {}


def convert_yolo(
    filename: str,
    text: str,
    names: dict[int, str],
    images_by_stem: dict[str, list[tuple[str, int, int]]],
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    stem = PureWindowsPath(_image_name(filename)).stem.casefold()
    matches = images_by_stem.get(stem, [])
    if len(matches) != 1:
        return {}, [f"{filename}: YOLO label filename must uniquely match an imported project image"]
    image_name, width, height = matches[0]
    result: list[dict[str, Any]] = []
    warnings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        try:
            class_id = int(parts[0])
            coords = [float(part) for part in parts[1:]]
        except (IndexError, TypeError, ValueError):
            warnings.append(f"{filename}:{line_number}: invalid numeric label")
            continue
        if class_id not in names or not names[class_id]:
            warnings.append(f"{filename}:{line_number}: class {class_id} absent from data.yaml")
            continue
        if not coords or any(not isfinite(value) or not 0 <= value <= 1 for value in coords):
            warnings.append(f"{filename}:{line_number}: coordinates must be normalized 0..1")
            continue
        label = names[class_id]
        record: dict[str, Any] = {
            "id": f"yolo:{filename}:{line_number}",
            "label_short_code": label,
            "label_long_code": label,
            "label_id": f"yolo:{class_id}",
            "verified": False,
            "data": {"external_format": "yolo", "external_class_index": class_id},
        }
        if len(coords) == 4:
            cx, cy, w, h = coords
            if w <= 0 or h <= 0:
                warnings.append(f"{filename}:{line_number}: empty YOLO box")
                continue
            record.update(
                type="RectangleAnnotation",
                top_left=[(cx - w / 2) * width, (cy - h / 2) * height],
                bottom_right=[(cx + w / 2) * width, (cy + h / 2) * height],
            )
        elif len(coords) >= 6 and len(coords) % 2 == 0:
            record.update(
                type="PolygonAnnotation",
                points=[[coords[i] * width, coords[i + 1] * height] for i in range(0, len(coords), 2)],
                holes=[],
            )
        else:
            warnings.append(f"{filename}:{line_number}: expected bbox or segmentation polygon")
            continue
        result.append(record)
    return {image_name: result}, warnings
