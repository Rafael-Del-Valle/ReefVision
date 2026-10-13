"""Fail-closed validation of immutable instance-segmentation holdout snapshots.

This does not run inference, decode masks or authorize candidate promotion. Raster
bytes must be checked by a trusted managed-project resolver before evaluation.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol


class SnapshotImage(Protocol):
    image_id: str
    split: str
    group_key: str | None
    width_px: int
    height_px: int
    image_sha256: str
    image_annotation_status: str
    mask_annotation_count: int
    mask_annotation_snapshot_json: list[dict[str, Any]]


@dataclass(frozen=True)
class VerifiedMaskReference:
    image_id: str
    mask_id: str
    class_id: str
    geometry_kind: str
    content_path: str | None
    content_sha256: str | None


@dataclass(frozen=True)
class SegmentationHoldout:
    split: str
    image_ids: tuple[str, ...]
    group_ids: tuple[str, ...]
    masks: tuple[VerifiedMaskReference, ...]


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _touches_or_crosses(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a)
    if ab_c * ab_d < 0 and cd_a * cd_b < 0:
        return True

    def between(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(
            p[1], r[1]
        )

    return any(
        value == 0 and between(p, q, r)
        for value, p, q, r in (
            (ab_c, a, c, b),
            (ab_d, a, d, b),
            (cd_a, c, a, d),
            (cd_b, c, b, d),
        )
    )


def _validate_polygon(vertices: object, *, width: int, height: int) -> None:
    if not isinstance(vertices, list):
        raise ValueError("Verified polygon is missing source-pixel coordinates")
    points: list[tuple[float, float]] = []
    for pair in vertices:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Invalid polygon vertex")
        x, y = pair
        if (
            not isinstance(x, (int, float))
            or isinstance(x, bool)
            or not isinstance(y, (int, float))
            or isinstance(y, bool)
            or not isfinite(x)
            or not isfinite(y)
            or not (0 <= x <= width and 0 <= y <= height)
        ):
            raise ValueError("Polygon vertex outside finite source-image bounds")
        points.append((float(x), float(y)))
    if len(points) > 3 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3 or len(set(points)) != len(points):
        raise ValueError("Polygon needs at least three unique source-pixel vertices")
    signed_double_area = sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True)
    )
    if abs(signed_double_area) <= 1e-8:
        raise ValueError("Polygon has zero source-pixel area")
    edges = [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges):
            if j <= i or j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if _touches_or_crosses(a, b, c, d):
                raise ValueError("Self-intersecting verified polygon cannot be evaluated")


def validate_segmentation_holdout(
    items: Sequence[SnapshotImage],
    *,
    split: str,
    minimum_images: int,
    minimum_masks: int,
    known_class_ids: Collection[str] | None,
    verify_raster: Callable[[str, str], None] | None,
) -> SegmentationHoldout:
    """Validate an entire dataset version and return verified holdout references.

    "items" must include all splits to catch group leakage. verify_raster must
    resolve a managed file and compare its exact digest; without it, fail closed.
    """
    if split not in {"validation", "test"} or minimum_images < 1 or minimum_masks < 1:
        raise ValueError("Invalid segmentation holdout split or minimum support")
    group_splits: dict[str, str] = {}
    seen_images: set[str] = set()
    seen_masks: set[str] = set()
    selected_images: list[str] = []
    selected_groups: set[str] = set()
    refs: list[VerifiedMaskReference] = []

    for item in items:
        if (
            not item.image_id
            or item.image_id in seen_images
            or item.width_px < 1
            or item.height_px < 1
            or not _digest(item.image_sha256)
            or item.split not in {"train", "validation", "test"}
        ):
            raise ValueError("Invalid or duplicated immutable snapshot image")
        seen_images.add(item.image_id)
        group = item.group_key or f"image:{item.image_id}"
        previous = group_splits.setdefault(group, item.split)
        if previous != item.split:
            raise ValueError("Dataset contains cross-split image-group leakage")
        if item.split != split:
            continue
        if item.image_annotation_status != "reviewed":
            raise ValueError("Holdout masks require a human-reviewed image")
        masks = item.mask_annotation_snapshot_json
        if not isinstance(masks, list) or item.mask_annotation_count != len(masks):
            raise ValueError("Holdout mask count differs from its immutable snapshot")
        selected_images.append(item.image_id)
        selected_groups.add(group)
        for mask in masks:
            if not isinstance(mask, dict):
                raise ValueError("Malformed verified mask snapshot")
            mask_id, class_id = mask.get("id"), mask.get("label_class_id")
            if (
                not isinstance(mask_id, str)
                or not mask_id
                or mask_id in seen_masks
                or not isinstance(class_id, str)
                or not class_id
            ):
                raise ValueError("Missing or duplicated verified mask identity/class")
            if known_class_ids is not None and class_id not in known_class_ids:
                raise ValueError("Mask references an unknown immutable project class")
            if mask.get("status") != "verified" or mask.get("source_type") == "evaluation_only":
                raise ValueError("Evaluation requires human-verified masks only")
            provenance = mask.get("provenance_json")
            if isinstance(provenance, dict) and provenance.get("evaluation_only"):
                raise ValueError("Evaluation-only outputs cannot become holdout ground truth")
            kind = mask.get("geometry_kind")
            path: str | None = None
            digest: str | None = None
            if kind == "polygon":
                _validate_polygon(
                    mask.get("polygon_json"),
                    width=item.width_px,
                    height=item.height_px,
                )
            elif kind == "raster_mask":
                path, digest = mask.get("mask_path"), mask.get("mask_content_sha256")
                if (
                    not isinstance(path, str)
                    or not path
                    or not _digest(digest)
                    or verify_raster is None
                ):
                    raise ValueError("Raster mask requires verified immutable content")
                verify_raster(path, digest)
            else:
                raise ValueError("Unsupported verified segmentation mask geometry")
            seen_masks.add(mask_id)
            refs.append(VerifiedMaskReference(item.image_id, mask_id, class_id, kind, path, digest))

    if len(selected_images) < minimum_images or len(refs) < minimum_masks:
        raise ValueError("Segmentation holdout has insufficient verified support")
    return SegmentationHoldout(
        split, tuple(selected_images), tuple(sorted(selected_groups)), tuple(refs)
    )
