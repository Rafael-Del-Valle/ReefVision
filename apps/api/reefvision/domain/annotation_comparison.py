"""Deterministic, source-neutral comparison of source-pixel box evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from reefvision.domain.mask_coverage_geometry import (
    PixelRuns,
    intersect_runs,
    run_area,
    subtract_runs,
    union_runs,
)

ReferenceSide = Literal["a", "b"]


@dataclass(frozen=True)
class BoxEvidence:
    evidence_id: str
    image_id: str
    class_id: str
    bounds: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.image_id or not self.class_id:
            raise ValueError("Evidence, image, and class identifiers are required")
        x_min, y_min, x_max, y_max = self.bounds
        if not all(isfinite(value) for value in self.bounds):
            raise ValueError("Box coordinates must be finite")
        if x_max <= x_min or y_max <= y_min:
            raise ValueError("Box evidence must have positive area")


@dataclass(frozen=True)
class BoxMatch:
    source_a_id: str
    source_b_id: str
    image_id: str
    iou: float


@dataclass(frozen=True)
class ClassComparison:
    count_a: int
    count_b: int
    signed_count_difference_b_minus_a: int
    absolute_count_difference: int
    reference_relative_percent_difference: float | None
    reference_relative_percent_reason: str | None
    matches: tuple[BoxMatch, ...]
    unmatched_a_ids: tuple[str, ...]
    unmatched_b_ids: tuple[str, ...]
    mean_matched_iou: float | None
    false_positive_ids: tuple[str, ...] | None
    false_negative_ids: tuple[str, ...] | None


@dataclass(frozen=True)
class BoxComparison:
    algorithm: str
    iou_threshold: float
    reference_side: ReferenceSide | None
    independent_sampling_unit: str
    per_class: dict[str, ClassComparison]


@dataclass(frozen=True)
class MaskEvidence:
    evidence_id: str
    image_id: str
    class_id: str
    width_px: int
    height_px: int
    runs: PixelRuns

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.image_id or not self.class_id:
            raise ValueError("Evidence, image, and class identifiers are required")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("Mask source dimensions must be positive")
        normalized = union_runs(self.runs)
        if not normalized:
            raise ValueError("Mask evidence must contain occupied pixels")
        if any(y >= self.height_px or end > self.width_px for y, _, end in normalized):
            raise ValueError("Mask runs exceed source dimensions")
        object.__setattr__(self, "runs", normalized)


@dataclass(frozen=True)
class MaskMatch:
    source_a_id: str
    source_b_id: str
    image_id: str
    iou: float
    intersection_area_pixels: int
    union_area_pixels: int


@dataclass(frozen=True)
class MaskClassComparison:
    count_a: int
    count_b: int
    signed_count_difference_b_minus_a: int
    absolute_count_difference: int
    reference_relative_percent_difference: float | None
    reference_relative_percent_reason: str | None
    matches: tuple[MaskMatch, ...]
    unmatched_a_ids: tuple[str, ...]
    unmatched_b_ids: tuple[str, ...]
    mean_matched_iou: float | None
    false_positive_ids: tuple[str, ...] | None
    false_negative_ids: tuple[str, ...] | None
    union_area_a_pixels: int
    union_area_b_pixels: int
    intersection_area_pixels: int
    union_area_pixels: int
    symmetric_difference_area_pixels: int
    union_iou: float | None
    union_iou_reason: str | None
    disagreement_runs: PixelRuns


@dataclass(frozen=True)
class MaskComparison:
    algorithm: str
    iou_threshold: float
    reference_side: ReferenceSide | None
    independent_sampling_unit: str
    per_class: dict[str, MaskClassComparison]


def _iou(first: BoxEvidence, second: BoxEvidence) -> float:
    ax1, ay1, ax2, ay2 = first.bounds
    bx1, by1, bx2, by2 = second.bounds
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0.0 else 0.0


def _validate_unique(items: list[BoxEvidence] | list[MaskEvidence], source_name: str) -> None:
    identifiers = [item.evidence_id for item in items]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{source_name} evidence identifiers must be unique")


def compare_box_evidence(
    source_a: list[BoxEvidence],
    source_b: list[BoxEvidence],
    *,
    iou_threshold: float,
    reference_side: ReferenceSide | None = None,
) -> BoxComparison:
    """Compare independent evidence inventories without assigning reviewer semantics."""

    if not isfinite(iou_threshold) or not 0.0 < iou_threshold <= 1.0:
        raise ValueError("IoU threshold must be finite and in (0, 1]")
    if reference_side not in {None, "a", "b"}:
        raise ValueError("Reference side must be 'a', 'b', or null")
    _validate_unique(source_a, "Source A")
    _validate_unique(source_b, "Source B")

    per_class: dict[str, ClassComparison] = {}
    class_ids = sorted({item.class_id for item in source_a + source_b})
    for class_id in class_ids:
        items_a = sorted(
            (item for item in source_a if item.class_id == class_id),
            key=lambda item: (item.image_id, item.evidence_id),
        )
        items_b = sorted(
            (item for item in source_b if item.class_id == class_id),
            key=lambda item: (item.image_id, item.evidence_id),
        )
        candidates = sorted(
            (
                (-_iou(item_a, item_b), item_a.evidence_id, item_b.evidence_id, item_a, item_b)
                for item_a in items_a
                for item_b in items_b
                if item_a.image_id == item_b.image_id
            ),
            key=lambda item: (item[0], item[1], item[2]),
        )
        matched_a: set[str] = set()
        matched_b: set[str] = set()
        matches: list[BoxMatch] = []
        for negative_iou, _, _, item_a, item_b in candidates:
            overlap = -negative_iou
            if overlap < iou_threshold:
                break
            if item_a.evidence_id in matched_a or item_b.evidence_id in matched_b:
                continue
            matched_a.add(item_a.evidence_id)
            matched_b.add(item_b.evidence_id)
            matches.append(
                BoxMatch(item_a.evidence_id, item_b.evidence_id, item_a.image_id, overlap)
            )
        matches.sort(key=lambda item: (item.image_id, item.source_a_id, item.source_b_id))
        unmatched_a = tuple(
            item.evidence_id for item in items_a if item.evidence_id not in matched_a
        )
        unmatched_b = tuple(
            item.evidence_id for item in items_b if item.evidence_id not in matched_b
        )
        count_a = len(items_a)
        count_b = len(items_b)
        reference_count = count_a if reference_side == "a" else count_b
        percent = None
        percent_reason = None
        if reference_side is not None:
            if reference_count == 0:
                percent_reason = "zero_reference_count"
            else:
                percent = (count_b - count_a) / reference_count * 100.0
        false_positive_ids: tuple[str, ...] | None = None
        false_negative_ids: tuple[str, ...] | None = None
        if reference_side == "a":
            false_positive_ids, false_negative_ids = unmatched_b, unmatched_a
        elif reference_side == "b":
            false_positive_ids, false_negative_ids = unmatched_a, unmatched_b
        per_class[class_id] = ClassComparison(
            count_a=count_a,
            count_b=count_b,
            signed_count_difference_b_minus_a=count_b - count_a,
            absolute_count_difference=abs(count_b - count_a),
            reference_relative_percent_difference=percent,
            reference_relative_percent_reason=percent_reason,
            matches=tuple(matches),
            unmatched_a_ids=unmatched_a,
            unmatched_b_ids=unmatched_b,
            mean_matched_iou=(
                sum(item.iou for item in matches) / len(matches) if matches else None
            ),
            false_positive_ids=false_positive_ids,
            false_negative_ids=false_negative_ids,
        )
    return BoxComparison(
        algorithm="reefvision.class-aware-box-comparison.v1",
        iou_threshold=iou_threshold,
        reference_side=reference_side,
        independent_sampling_unit="image",
        per_class=per_class,
    )


def _mask_iou(first: MaskEvidence, second: MaskEvidence) -> tuple[float, int, int]:
    if (
        first.image_id != second.image_id
        or first.width_px != second.width_px
        or first.height_px != second.height_px
    ):
        return 0.0, 0, run_area(union_runs(first.runs, second.runs))
    intersection = run_area(intersect_runs(first.runs, second.runs))
    union = run_area(union_runs(first.runs, second.runs))
    return (intersection / union if union else 0.0), intersection, union


def compare_mask_evidence(
    source_a: list[MaskEvidence],
    source_b: list[MaskEvidence],
    *,
    iou_threshold: float,
    reference_side: ReferenceSide | None = None,
) -> MaskComparison:
    """Compare exact source-pixel masks without double-counting class unions."""
    if not isfinite(iou_threshold) or not 0.0 < iou_threshold <= 1.0:
        raise ValueError("IoU threshold must be finite and in (0, 1]")
    if reference_side not in {None, "a", "b"}:
        raise ValueError("Reference side must be 'a', 'b', or omitted")
    _validate_unique(source_a, "Source A")
    _validate_unique(source_b, "Source B")
    dimensions = {(item.image_id, item.width_px, item.height_px) for item in source_a + source_b}
    by_image = {item[0] for item in dimensions}
    if any(sum(entry[0] == image_id for entry in dimensions) > 1 for image_id in by_image):
        raise ValueError("Mask source dimensions are incompatible")
    per_class: dict[str, MaskClassComparison] = {}
    for class_id in sorted({item.class_id for item in source_a + source_b}):
        items_a = sorted(
            (item for item in source_a if item.class_id == class_id),
            key=lambda item: (item.image_id, item.evidence_id),
        )
        items_b = sorted(
            (item for item in source_b if item.class_id == class_id),
            key=lambda item: (item.image_id, item.evidence_id),
        )
        candidates = []
        for item_a in items_a:
            for item_b in items_b:
                if item_a.image_id != item_b.image_id:
                    continue
                overlap, intersection, union = _mask_iou(item_a, item_b)
                candidates.append(
                    (-overlap, item_a.evidence_id, item_b.evidence_id, intersection, union)
                )
        candidates.sort()
        by_a = {item.evidence_id: item for item in items_a}
        matched_a: set[str] = set()
        matched_b: set[str] = set()
        matches: list[MaskMatch] = []
        for negative_iou, a_id, b_id, intersection, union in candidates:
            overlap = -negative_iou
            if overlap < iou_threshold:
                break
            if a_id in matched_a or b_id in matched_b:
                continue
            matched_a.add(a_id)
            matched_b.add(b_id)
            matches.append(MaskMatch(a_id, b_id, by_a[a_id].image_id, overlap, intersection, union))
        unmatched_a = tuple(
            item.evidence_id for item in items_a if item.evidence_id not in matched_a
        )
        unmatched_b = tuple(
            item.evidence_id for item in items_b if item.evidence_id not in matched_b
        )
        union_a = union_runs(*(item.runs for item in items_a))
        union_b = union_runs(*(item.runs for item in items_b))
        shared_runs = intersect_runs(union_a, union_b)
        combined_runs = union_runs(union_a, union_b)
        disagreement = union_runs(subtract_runs(union_a, union_b), subtract_runs(union_b, union_a))
        area_a = run_area(union_a)
        area_b = run_area(union_b)
        intersection_area = run_area(shared_runs)
        union_area = run_area(combined_runs)
        count_a, count_b = len(items_a), len(items_b)
        reference_count = count_a if reference_side == "a" else count_b
        percent = None
        percent_reason = None
        if reference_side is not None:
            if reference_count == 0:
                percent_reason = "zero_reference_count"
            else:
                percent = (count_b - count_a) / reference_count * 100.0
        false_positive_ids: tuple[str, ...] | None = None
        false_negative_ids: tuple[str, ...] | None = None
        if reference_side == "a":
            false_positive_ids, false_negative_ids = unmatched_b, unmatched_a
        elif reference_side == "b":
            false_positive_ids, false_negative_ids = unmatched_a, unmatched_b
        per_class[class_id] = MaskClassComparison(
            count_a=count_a,
            count_b=count_b,
            signed_count_difference_b_minus_a=count_b - count_a,
            absolute_count_difference=abs(count_b - count_a),
            reference_relative_percent_difference=percent,
            reference_relative_percent_reason=percent_reason,
            matches=tuple(matches),
            unmatched_a_ids=unmatched_a,
            unmatched_b_ids=unmatched_b,
            mean_matched_iou=(
                sum(item.iou for item in matches) / len(matches) if matches else None
            ),
            false_positive_ids=false_positive_ids,
            false_negative_ids=false_negative_ids,
            union_area_a_pixels=area_a,
            union_area_b_pixels=area_b,
            intersection_area_pixels=intersection_area,
            union_area_pixels=union_area,
            symmetric_difference_area_pixels=run_area(disagreement),
            union_iou=(intersection_area / union_area if union_area else None),
            union_iou_reason=(None if union_area else "both_source_unions_empty"),
            disagreement_runs=disagreement,
        )
    return MaskComparison(
        algorithm="reefvision.class-aware-mask-comparison.v1",
        iou_threshold=iou_threshold,
        reference_side=reference_side,
        independent_sampling_unit="image",
        per_class=per_class,
    )
