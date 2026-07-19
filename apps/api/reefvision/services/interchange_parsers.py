"""Normalize supported external annotation formats into one import graph."""

from __future__ import annotations

import base64
import io
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.schemas.interchange import InterchangeFormat


@dataclass(slots=True)
class SourceCategory:
    key: str
    name: str


@dataclass(slots=True)
class SourceImage:
    key: str
    filename: str
    width: int | None = None
    height: int | None = None
    reefvision_image_id: str | None = None


@dataclass(slots=True)
class SourceAnnotation:
    source_id: str
    image_key: str
    category_key: str
    geometry_kind: str
    bbox: tuple[float, float, float, float] | None = None
    polygon: list[list[float]] | None = None
    raster: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedInterchange:
    categories: list[SourceCategory]
    images: list[SourceImage]
    annotations: list[SourceAnnotation]
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be numeric") from exc
    if not np.isfinite(number):
        raise ValidationError(f"{label} must be finite")
    return number


def _bbox_xywh(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValidationError("COCO bounding boxes must contain x, y, width, and height")
    x, y, width, height = (_float(item, "Bounding-box coordinate") for item in value)
    if width <= 0 or height <= 0:
        raise ValidationError("Bounding boxes must have positive width and height")
    return x, y, x + width, y + height


def _polygon_from_flat(values: Any) -> list[list[float]]:
    if not isinstance(values, list) or len(values) < 6 or len(values) % 2:
        raise ValidationError("Polygon segmentation must contain at least three coordinate pairs")
    points = [
        [_float(values[index], "Polygon x"), _float(values[index + 1], "Polygon y")]
        for index in range(0, len(values), 2)
    ]
    if len(points) > 3 and points[0] == points[-1]:
        points = points[:-1]
    if len({(point[0], point[1]) for point in points}) < 3:
        raise ValidationError("Polygons must contain at least three unique points")
    return points


def _decode_uncompressed_rle(segmentation: dict[str, Any]) -> np.ndarray:
    size = segmentation.get("size")
    counts = segmentation.get("counts")
    if not isinstance(size, list) or len(size) != 2:
        raise ValidationError("COCO RLE masks require a [height, width] size")
    if not isinstance(counts, list):
        raise ValidationError(
            "Compressed COCO RLE strings are not accepted directly; expand counts before import"
        )
    height, width = int(size[0]), int(size[1])
    if height <= 0 or width <= 0:
        raise ValidationError("COCO RLE dimensions must be positive")
    values = np.zeros(height * width, dtype=np.uint8)
    cursor = 0
    current = 0
    for raw_count in counts:
        count = int(raw_count)
        if count < 0 or cursor + count > values.size:
            raise ValidationError("COCO RLE counts exceed the declared mask size")
        if current:
            values[cursor : cursor + count] = 1
        cursor += count
        current = 1 - current
    if cursor != values.size:
        raise ValidationError("COCO RLE counts do not cover the declared mask size")
    return values.reshape((width, height)).T.astype(bool)


def _panoptic_rgb_to_ids(encoded: str) -> np.ndarray:
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.int64)
    except Exception as exc:
        raise ValidationError("A panoptic mask could not be decoded as base64 PNG") from exc
    return rgb[..., 0] + 256 * rgb[..., 1] + 65536 * rgb[..., 2]


def _parse_coco(document: dict[str, Any], *, panoptic: bool) -> ParsedInterchange:
    categories_raw = document.get("categories", [])
    images_raw = document.get("images", [])
    annotations_raw = document.get("annotations", [])
    if not isinstance(categories_raw, list) or not isinstance(images_raw, list):
        raise ValidationError("COCO documents require category and image arrays")
    categories = [
        SourceCategory(key=str(item["id"]), name=str(item["name"]))
        for item in categories_raw
        if isinstance(item, dict) and "id" in item and "name" in item
    ]
    images = [
        SourceImage(
            key=str(item["id"]),
            filename=Path(str(item.get("file_name") or item.get("name") or item["id"])).name,
            width=int(item["width"]) if item.get("width") is not None else None,
            height=int(item["height"]) if item.get("height") is not None else None,
            reefvision_image_id=(
                str(item["reefvision_image_id"]) if item.get("reefvision_image_id") else None
            ),
        )
        for item in images_raw
        if isinstance(item, dict) and "id" in item
    ]
    annotations: list[SourceAnnotation] = []
    warnings: list[str] = []
    panoptic_masks = document.get("panoptic_masks", {})
    if panoptic and not isinstance(panoptic_masks, dict):
        raise ValidationError("panoptic_masks must map annotation filenames to base64 PNG data")
    for index, item in enumerate(annotations_raw if isinstance(annotations_raw, list) else []):
        if not isinstance(item, dict) or "image_id" not in item:
            continue
        source_id = str(item.get("id", index + 1))
        if panoptic and isinstance(item.get("segments_info"), list):
            mask_name = str(item.get("file_name", ""))
            encoded = panoptic_masks.get(mask_name)
            if not isinstance(encoded, str):
                warnings.append(
                    f"Panoptic annotation {source_id} has no base64 mask for {mask_name}"
                )
                continue
            ids = _panoptic_rgb_to_ids(encoded)
            for segment in item["segments_info"]:
                if (
                    not isinstance(segment, dict)
                    or "id" not in segment
                    or "category_id" not in segment
                ):
                    continue
                segment_id = int(segment["id"])
                raster = ids == segment_id
                if not raster.any():
                    warnings.append(f"Panoptic segment {segment_id} is empty")
                    continue
                annotations.append(
                    SourceAnnotation(
                        source_id=f"{source_id}:{segment_id}",
                        image_key=str(item["image_id"]),
                        category_key=str(segment["category_id"]),
                        geometry_kind="raster_mask",
                        raster=raster,
                        metadata={"segment_id": segment_id, "iscrowd": segment.get("iscrowd", 0)},
                    )
                )
            continue
        if "category_id" not in item:
            continue
        bbox = _bbox_xywh(item["bbox"]) if item.get("bbox") is not None else None
        segmentation = item.get("segmentation")
        if isinstance(segmentation, list) and segmentation:
            polygons = [
                entry for entry in segmentation if isinstance(entry, list) and len(entry) >= 6
            ]
            if not polygons:
                warnings.append(f"COCO annotation {source_id} has no valid polygon")
                continue
            for polygon_index, polygon in enumerate(polygons):
                annotations.append(
                    SourceAnnotation(
                        source_id=f"{source_id}:{polygon_index}",
                        image_key=str(item["image_id"]),
                        category_key=str(item["category_id"]),
                        geometry_kind="polygon",
                        bbox=bbox,
                        polygon=_polygon_from_flat(polygon),
                        metadata={"iscrowd": item.get("iscrowd", 0)},
                    )
                )
        elif isinstance(segmentation, dict):
            annotations.append(
                SourceAnnotation(
                    source_id=source_id,
                    image_key=str(item["image_id"]),
                    category_key=str(item["category_id"]),
                    geometry_kind="raster_mask",
                    bbox=bbox,
                    raster=_decode_uncompressed_rle(segmentation),
                    metadata={"iscrowd": item.get("iscrowd", 0)},
                )
            )
        elif bbox is not None:
            annotations.append(
                SourceAnnotation(
                    source_id=source_id,
                    image_key=str(item["image_id"]),
                    category_key=str(item["category_id"]),
                    geometry_kind="bounding_box",
                    bbox=bbox,
                    metadata={"iscrowd": item.get("iscrowd", 0)},
                )
            )
        else:
            warnings.append(f"COCO annotation {source_id} has no supported geometry")
    return ParsedInterchange(categories, images, annotations, warnings=warnings)


def _parse_cvat(document: dict[str, Any]) -> ParsedInterchange:
    xml_text = document.get("xml")
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise ValidationError("CVAT import requires document.xml")
    try:
        root = element_tree.fromstring(xml_text)
    except element_tree.ParseError as exc:
        raise ValidationError(f"CVAT XML is invalid: {exc}") from exc
    labels = sorted(
        {
            str(element.attrib.get("label", "")).strip()
            for element in root.findall(".//image/*")
            if element.tag in {"box", "polygon"} and element.attrib.get("label")
        }
    )
    categories = [SourceCategory(key=label, name=label) for label in labels]
    images: list[SourceImage] = []
    annotations: list[SourceAnnotation] = []
    for image_element in root.findall(".//image"):
        key = str(image_element.attrib.get("id", len(images)))
        filename = Path(str(image_element.attrib.get("name", key))).name
        width = (
            int(float(image_element.attrib["width"])) if image_element.attrib.get("width") else None
        )
        height = (
            int(float(image_element.attrib["height"]))
            if image_element.attrib.get("height")
            else None
        )
        images.append(SourceImage(key=key, filename=filename, width=width, height=height))
        for shape_index, shape in enumerate(image_element):
            label = str(shape.attrib.get("label", "")).strip()
            if not label:
                continue
            source_id = f"{key}:{shape_index}"
            if shape.tag == "box":
                bbox = (
                    _float(shape.attrib.get("xtl"), "CVAT xtl"),
                    _float(shape.attrib.get("ytl"), "CVAT ytl"),
                    _float(shape.attrib.get("xbr"), "CVAT xbr"),
                    _float(shape.attrib.get("ybr"), "CVAT ybr"),
                )
                annotations.append(
                    SourceAnnotation(source_id, key, label, "bounding_box", bbox=bbox)
                )
            elif shape.tag == "polygon":
                points_text = str(shape.attrib.get("points", ""))
                polygon = [
                    [
                        _float(pair.split(",")[0], "CVAT polygon x"),
                        _float(pair.split(",")[1], "CVAT polygon y"),
                    ]
                    for pair in points_text.split(";")
                    if "," in pair
                ]
                if len(polygon) >= 3:
                    annotations.append(
                        SourceAnnotation(source_id, key, label, "polygon", polygon=polygon)
                    )
    return ParsedInterchange(categories, images, annotations)


def _labelme_documents(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("documents")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return [document]


def _parse_labelme(document: dict[str, Any]) -> ParsedInterchange:
    documents = _labelme_documents(document)
    labels = sorted(
        {
            str(shape.get("label", "")).strip()
            for item in documents
            for shape in item.get("shapes", [])
            if isinstance(shape, dict) and shape.get("label")
        }
    )
    categories = [SourceCategory(key=label, name=label) for label in labels]
    images: list[SourceImage] = []
    annotations: list[SourceAnnotation] = []
    for image_index, item in enumerate(documents):
        key = str(item.get("imageId", image_index))
        filename = Path(str(item.get("imagePath", key))).name
        images.append(
            SourceImage(
                key=key,
                filename=filename,
                width=int(item["imageWidth"]) if item.get("imageWidth") else None,
                height=int(item["imageHeight"]) if item.get("imageHeight") else None,
            )
        )
        for shape_index, shape in enumerate(item.get("shapes", [])):
            if not isinstance(shape, dict) or not shape.get("label"):
                continue
            points = shape.get("points")
            if not isinstance(points, list):
                continue
            source_id = f"{key}:{shape_index}"
            shape_type = str(shape.get("shape_type", "polygon"))
            if shape_type == "rectangle" and len(points) >= 2:
                first, second = points[0], points[1]
                x_values = [_float(first[0], "LabelMe x"), _float(second[0], "LabelMe x")]
                y_values = [_float(first[1], "LabelMe y"), _float(second[1], "LabelMe y")]
                annotations.append(
                    SourceAnnotation(
                        source_id,
                        key,
                        str(shape["label"]),
                        "bounding_box",
                        bbox=(min(x_values), min(y_values), max(x_values), max(y_values)),
                    )
                )
            elif len(points) >= 3:
                polygon = [
                    [_float(point[0], "LabelMe polygon x"), _float(point[1], "LabelMe polygon y")]
                    for point in points
                ]
                annotations.append(
                    SourceAnnotation(
                        source_id, key, str(shape["label"]), "polygon", polygon=polygon
                    )
                )
    return ParsedInterchange(categories, images, annotations)


def _parse_roboflow_yolo(document: dict[str, Any]) -> ParsedInterchange:
    class_names = document.get("classes", [])
    labels = document.get("labels", {})
    dimensions = document.get("image_dimensions", {})
    if not isinstance(class_names, list) or not isinstance(labels, dict):
        raise ValidationError("Roboflow YOLO import requires classes and labels")
    categories = [SourceCategory(str(index), str(name)) for index, name in enumerate(class_names)]
    images: list[SourceImage] = []
    annotations: list[SourceAnnotation] = []
    warnings: list[str] = []
    for image_index, (filename_raw, raw_lines) in enumerate(labels.items()):
        filename = Path(str(filename_raw)).name
        size = dimensions.get(filename_raw) or dimensions.get(filename)
        width = int(size[0]) if isinstance(size, list) and len(size) == 2 else None
        height = int(size[1]) if isinstance(size, list) and len(size) == 2 else None
        key = str(image_index)
        images.append(SourceImage(key, filename, width, height))
        if width is None or height is None:
            warnings.append(f"Roboflow YOLO image {filename} has no image_dimensions entry")
            continue
        lines = raw_lines.splitlines() if isinstance(raw_lines, str) else raw_lines
        for line_index, raw_line in enumerate(lines if isinstance(lines, list) else []):
            values = str(raw_line).strip().split()
            if len(values) < 5:
                continue
            category_key = values[0]
            coordinates = [_float(value, "YOLO coordinate") for value in values[1:]]
            source_id = f"{key}:{line_index}"
            if len(coordinates) == 4:
                center_x, center_y, normalized_width, normalized_height = coordinates
                x_min = (center_x - normalized_width / 2.0) * width
                y_min = (center_y - normalized_height / 2.0) * height
                x_max = (center_x + normalized_width / 2.0) * width
                y_max = (center_y + normalized_height / 2.0) * height
                annotations.append(
                    SourceAnnotation(
                        source_id,
                        key,
                        category_key,
                        "bounding_box",
                        bbox=(x_min, y_min, x_max, y_max),
                    )
                )
            elif len(coordinates) >= 6 and len(coordinates) % 2 == 0:
                polygon = [
                    [coordinates[index] * width, coordinates[index + 1] * height]
                    for index in range(0, len(coordinates), 2)
                ]
                annotations.append(
                    SourceAnnotation(source_id, key, category_key, "polygon", polygon=polygon)
                )
    return ParsedInterchange(categories, images, annotations, warnings=warnings)


def parse_interchange(
    format_name: InterchangeFormat, document: dict[str, Any]
) -> ParsedInterchange:
    if format_name in {"coco_detection", "coco_instance", "roboflow_coco"}:
        return _parse_coco(document, panoptic=False)
    if format_name == "coco_panoptic":
        return _parse_coco(document, panoptic=True)
    if format_name == "cvat":
        return _parse_cvat(document)
    if format_name == "labelme":
        return _parse_labelme(document)
    if format_name == "roboflow_yolo":
        return _parse_roboflow_yolo(document)
    raise ValidationError("Unsupported interchange format")
