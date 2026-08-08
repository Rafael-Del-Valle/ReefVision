#!/usr/bin/env python3
"""Preflight Rafael Del Valle's CoralNet-Toolbox thesis annotation export for ReefVision."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml

THESIS_CLASSES = {
    "Muricea C",
    "Muricea O",
    "Swiftia C",
    "Swiftia O",
    "Thesea C",
    "Thesea O",
}
SUPPORTED_TYPES = {
    "RectangleAnnotation",
    "PatchAnnotation",
    "PolygonAnnotation",
    "MultiPolygonAnnotation",
    "MaskAnnotation",
}
LOCK_BIT = 128


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a CoralNet-Toolbox thesis annotation JSON together with "
            "class_mapping.json and data.yaml before importing into ReefVision."
        )
    )
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--class-mapping", required=True, type=Path)
    parser.add_argument("--data-yaml", required=True, type=Path)
    parser.add_argument(
        "--images",
        type=Path,
        default=None,
        help="Optional image directory; searched recursively by basename.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path for the JSON validation report.",
    )
    return parser.parse_args()


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a top-level JSON object")
    return value


def parse_yaml_names(path: Path) -> dict[int, str]:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    names = value.get("names")
    if isinstance(names, list):
        return {index: str(name) for index, name in enumerate(names)}
    if not isinstance(names, dict):
        raise ValueError(f"{path} has no usable names mapping")
    parsed: dict[int, str] = {}
    for raw_index, raw_name in names.items():
        parsed[int(raw_index)] = str(raw_name)
    return parsed


def basename(reference: str) -> str:
    windows_name = PureWindowsPath(reference).name
    if windows_name:
        return windows_name
    return Path(reference.replace("\\", "/")).name


def class_mapping_index(mapping: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    by_short: dict[str, dict[str, Any]] = {}
    id_to_short: dict[str, str] = {}
    for key, raw_entry in mapping.items():
        if not isinstance(raw_entry, dict):
            continue
        short_code = str(raw_entry.get("short_label_code") or key).strip()
        by_short[short_code] = raw_entry
        external_id = str(raw_entry.get("id") or "").strip()
        if external_id:
            id_to_short[external_id] = short_code
    return by_short, id_to_short


def image_basename_index(root: Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for path in root.rglob("*"):
        if path.is_file():
            index[path.name.casefold()].append(str(path.resolve()))
    return index


def validate() -> tuple[dict[str, Any], int]:
    args = parse_args()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        annotations = load_json_object(args.annotations)
        mapping = load_json_object(args.class_mapping)
        yaml_names = parse_yaml_names(args.data_yaml)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        report = {"status": "FAIL", "errors": [str(exc)], "warnings": []}
        print(json.dumps(report, indent=2, sort_keys=True))
        return report, 2

    by_short, id_to_short = class_mapping_index(mapping)
    mapping_classes = set(by_short)
    yaml_classes = set(yaml_names.values())
    if mapping_classes != THESIS_CLASSES:
        errors.append(
            "class_mapping.json does not contain exactly the six thesis classes: "
            f"missing={sorted(THESIS_CLASSES - mapping_classes)}, "
            f"extra={sorted(mapping_classes - THESIS_CLASSES)}"
        )
    if yaml_classes != THESIS_CLASSES:
        errors.append(
            "data.yaml names do not contain exactly the six thesis classes: "
            f"missing={sorted(THESIS_CLASSES - yaml_classes)}, "
            f"extra={sorted(yaml_classes - THESIS_CLASSES)}"
        )
    if len(set(yaml_names)) != len(yaml_names):
        errors.append("data.yaml contains duplicate class indices")
    if len(id_to_short) != len(by_short):
        errors.append("class_mapping.json has missing or duplicate external class UUIDs")

    annotation_type_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    annotation_ids: Counter[str] = Counter()
    image_annotation_counts: dict[str, int] = {}
    image_references: list[str] = []
    polygon_hole_annotations = 0
    polygon_hole_count = 0
    semantic_annotations = 0
    semantic_rle_parts = 0
    unsupported_annotations = 0
    malformed_annotations = 0

    for image_reference, raw_entries in annotations.items():
        reference = str(image_reference)
        image_references.append(reference)
        if not isinstance(raw_entries, list):
            errors.append(f"{reference}: annotations value is not a list")
            image_annotation_counts[reference] = 0
            continue
        image_annotation_counts[reference] = len(raw_entries)
        for raw_annotation in raw_entries:
            if not isinstance(raw_annotation, dict):
                malformed_annotations += 1
                errors.append(f"{reference}: annotation entry is not an object")
                continue
            external_type = str(raw_annotation.get("type") or "")
            annotation_type_counts[external_type or "<missing>"] += 1
            if external_type not in SUPPORTED_TYPES:
                unsupported_annotations += 1
                errors.append(f"{reference}: unsupported annotation type {external_type!r}")

            annotation_id = str(raw_annotation.get("id") or "").strip()
            if not annotation_id:
                errors.append(f"{reference}: annotation has no external ID")
            else:
                annotation_ids[annotation_id] += 1

            if external_type == "MaskAnnotation":
                semantic_annotations += 1
                shape = raw_annotation.get("shape")
                if not isinstance(shape, (list, tuple)) or len(shape) != 2:
                    errors.append(f"{reference}/{annotation_id}: semantic mask has invalid shape")
                label_map = raw_annotation.get("label_map")
                rle_masks = raw_annotation.get("rle_masks")
                if not isinstance(label_map, dict):
                    errors.append(f"{reference}/{annotation_id}: semantic mask has no label_map")
                    label_map = {}
                if not isinstance(rle_masks, list):
                    errors.append(f"{reference}/{annotation_id}: semantic mask has no rle_masks list")
                    rle_masks = []
                semantic_rle_parts += len(rle_masks)
                for part in rle_masks:
                    if not isinstance(part, dict):
                        errors.append(f"{reference}/{annotation_id}: malformed semantic RLE part")
                        continue
                    try:
                        stored_class_id = int(part.get("class_id"))
                    except (TypeError, ValueError):
                        errors.append(f"{reference}/{annotation_id}: invalid semantic class_id")
                        continue
                    real_class_id = stored_class_id % LOCK_BIT
                    if real_class_id == 0:
                        continue
                    short_code = str(
                        label_map.get(str(real_class_id))
                        or label_map.get(real_class_id)
                        or label_map.get(str(stored_class_id))
                        or label_map.get(stored_class_id)
                        or ""
                    ).strip()
                    if not short_code:
                        errors.append(
                            f"{reference}/{annotation_id}: class {real_class_id} missing from label_map"
                        )
                    elif short_code not in by_short:
                        errors.append(
                            f"{reference}/{annotation_id}: semantic label {short_code!r} "
                            "is absent from class_mapping.json"
                        )
                    else:
                        class_counts[short_code] += 1
                    rle = part.get("rle")
                    if not isinstance(rle, dict) or not isinstance(rle.get("counts"), str):
                        errors.append(f"{reference}/{annotation_id}: semantic RLE counts are missing")
                continue

            short_code = str(raw_annotation.get("label_short_code") or "").strip()
            label_id = str(raw_annotation.get("label_id") or "").strip()
            if not short_code and label_id:
                short_code = id_to_short.get(label_id, "")
            if not short_code:
                errors.append(f"{reference}/{annotation_id}: annotation has no resolvable class")
            elif short_code not in by_short:
                errors.append(
                    f"{reference}/{annotation_id}: class {short_code!r} is absent from class_mapping.json"
                )
            else:
                class_counts[short_code] += 1
                mapped_id = str(by_short[short_code].get("id") or "")
                if label_id and mapped_id and label_id != mapped_id:
                    errors.append(
                        f"{reference}/{annotation_id}: label UUID does not match {short_code}"
                    )

            if external_type == "PolygonAnnotation":
                points = raw_annotation.get("points")
                if not isinstance(points, list) or len(points) < 3:
                    errors.append(f"{reference}/{annotation_id}: polygon has fewer than 3 points")
                holes = raw_annotation.get("holes") or []
                if holes:
                    if not isinstance(holes, list):
                        errors.append(f"{reference}/{annotation_id}: polygon holes are malformed")
                    else:
                        polygon_hole_annotations += 1
                        polygon_hole_count += len(holes)
            elif external_type == "MultiPolygonAnnotation":
                polygons = raw_annotation.get("polygons")
                if not isinstance(polygons, list) or not polygons:
                    errors.append(f"{reference}/{annotation_id}: multipolygon has no polygon parts")
                else:
                    for part in polygons:
                        if not isinstance(part, dict):
                            errors.append(f"{reference}/{annotation_id}: malformed multipolygon part")
                            continue
                        points = part.get("points")
                        if not isinstance(points, list) or len(points) < 3:
                            errors.append(
                                f"{reference}/{annotation_id}: multipolygon part has fewer than 3 points"
                            )
                        holes = part.get("holes") or []
                        if isinstance(holes, list) and holes:
                            polygon_hole_annotations += 1
                            polygon_hole_count += len(holes)
            elif external_type == "RectangleAnnotation":
                if raw_annotation.get("top_left") is None or raw_annotation.get("bottom_right") is None:
                    errors.append(f"{reference}/{annotation_id}: rectangle coordinates are missing")
            elif external_type == "PatchAnnotation":
                if raw_annotation.get("center_xy") is None or raw_annotation.get("annotation_size") is None:
                    errors.append(f"{reference}/{annotation_id}: patch geometry is missing")

    duplicate_annotation_ids = sorted(
        annotation_id for annotation_id, count in annotation_ids.items() if count > 1
    )
    if duplicate_annotation_ids:
        errors.append(
            f"duplicate external annotation IDs detected: {duplicate_annotation_ids[:20]}"
        )

    unmatched_images: list[str] = []
    ambiguous_images: list[str] = []
    if args.images is not None:
        if not args.images.is_dir():
            errors.append(f"image directory does not exist: {args.images}")
        else:
            local_images = image_basename_index(args.images)
            for reference in image_references:
                matches = local_images.get(basename(reference).casefold(), [])
                if not matches:
                    unmatched_images.append(reference)
                elif len(matches) > 1:
                    ambiguous_images.append(reference)
            if unmatched_images:
                errors.append(f"{len(unmatched_images)} image references have no basename match")
            if ambiguous_images:
                errors.append(f"{len(ambiguous_images)} image references have ambiguous basename matches")
    else:
        warnings.append(
            "No --images directory supplied; source-image matching could not be checked on disk."
        )

    missing_observed_classes = sorted(THESIS_CLASSES - set(class_counts))
    if missing_observed_classes:
        warnings.append(
            "No annotations were observed for these thesis classes: "
            + ", ".join(missing_observed_classes)
        )

    report: dict[str, Any] = {
        "status": "PASS" if not errors else "FAIL",
        "files": {
            "annotations": str(args.annotations),
            "class_mapping": str(args.class_mapping),
            "data_yaml": str(args.data_yaml),
            "images": str(args.images) if args.images else None,
        },
        "summary": {
            "image_reference_count": len(image_references),
            "annotation_count": sum(image_annotation_counts.values()),
            "unique_annotation_id_count": len(annotation_ids),
            "annotation_type_counts": dict(sorted(annotation_type_counts.items())),
            "class_counts": {name: class_counts.get(name, 0) for name in sorted(THESIS_CLASSES)},
            "polygon_annotations_with_holes": polygon_hole_annotations,
            "polygon_hole_count": polygon_hole_count,
            "semantic_mask_annotations": semantic_annotations,
            "semantic_rle_parts": semantic_rle_parts,
            "unsupported_annotations": unsupported_annotations,
            "malformed_annotations": malformed_annotations,
            "unmatched_image_references": len(unmatched_images),
            "ambiguous_image_references": len(ambiguous_images),
        },
        "yaml_class_indices": {str(index): name for index, name in sorted(yaml_names.items())},
        "errors": errors,
        "warnings": warnings,
        "unmatched_images": unmatched_images,
        "ambiguous_images": ambiguous_images,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    return report, 0 if not errors else 1


if __name__ == "__main__":
    _, exit_code = validate()
    raise SystemExit(exit_code)
