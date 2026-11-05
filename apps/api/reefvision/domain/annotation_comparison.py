"""Deterministic, source-neutral comparison of source-pixel box evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

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


def _iou(first: BoxEvidence, second: BoxEvidence) -> float:
    ax1, ay1, ax2, ay2 = first.bounds
    bx1, by1, bx2, by2 = second.bounds
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0.0 else 0.0


def _validate_unique(items: list[BoxEvidence], source_name: str) -> None:
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
