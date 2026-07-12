"""Quality-control rule execution, run management, and issue workflows."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor, isfinite
from statistics import median
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    DatasetVersion,
    DatasetVersionItem,
    ImageAsset,
    Job,
    LabelClass,
    PredictionProposal,
    Project,
    QualityControlIssue,
    QualityControlRun,
)
from reefvision.domain.enums import (
    QUALITY_CONTROL_RULE_CATEGORIES,
    QualityControlRuleCategory,
    QualityControlSeverity,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.dataset_versions import DatasetVersionRepository
from reefvision.repositories.jobs import JobRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.repositories.quality_control import QualityControlRepository
from reefvision.schemas.quality_control import (
    QualityControlIssueAcknowledgeRequest,
    QualityControlIssueDismissRequest,
    QualityControlIssuePageResponse,
    QualityControlIssueResponse,
    QualityControlRunComparisonIssue,
    QualityControlRunComparisonResponse,
    QualityControlRunCreateRequest,
    QualityControlRunResponse,
    QualityControlThresholdConfig,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

CURRENT_QC_RULESET_VERSION = "1.0.0"
ALLOWED_SPLITS = ("train", "validation", "test", "unassigned")
SEVERITY_SCORES: dict[str, float] = {"error": 1.0, "warning": 0.6, "info": 0.3}


@dataclass(slots=True)
class EvaluatedImage:
    image_id: str
    project_id: str
    dataset_version_id: str | None
    original_filename: str
    width_px: int
    height_px: int
    annotation_status: str
    group_key: str | None
    split: str | None
    managed_path: str | None
    thumbnail_path: str | None
    sha256: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(slots=True)
class EvaluatedAnnotation:
    id: str
    image_id: str
    label_class_id: str | None
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    source_type: str
    source_model_id: str | None
    source_prediction_id: str | None
    provenance_json: dict[str, Any] | None
    revision: int


@dataclass(slots=True)
class EvaluatedPrediction:
    id: str
    project_id: str
    image_id: str
    model_id: str
    label_class_id: str | None
    predicted_label: str
    predicted_index: int | None
    confidence: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    review_status: str
    was_edited: bool
    reviewer_action_at: datetime | None
    accepted_annotation_id: str | None
    provenance_json: dict[str, Any] | None
    created_at: datetime


@dataclass(slots=True)
class QualityControlContext:
    project: Project
    settings: Settings
    scope_type: str
    dataset_version: DatasetVersion | None
    images: list[EvaluatedImage]
    annotations: list[EvaluatedAnnotation]
    predictions: list[EvaluatedPrediction]
    dataset_versions: list[DatasetVersion]
    dataset_version_items_by_version: dict[str, list[DatasetVersionItem]]
    images_by_id: dict[str, EvaluatedImage]
    live_images_by_id: dict[str, ImageAsset]
    annotations_by_image: dict[str, list[EvaluatedAnnotation]]
    predictions_by_image: dict[str, list[EvaluatedPrediction]]
    label_classes_by_id: dict[str, LabelClass]


@dataclass(slots=True)
class PendingIssue:
    rule_id: str
    rule_version: str
    severity: str
    title: str
    explanation: str
    project_id: str
    dataset_version_id: str | None
    image_id: str | None
    annotation_ids: list[str]
    prediction_ids: list[str]
    class_ids: list[str]
    measured_values: dict[str, Any]
    thresholds: dict[str, Any]
    fingerprint_payload: dict[str, Any]


class QualityControlRule:
    rule_id: str
    rule_version: str
    category: QualityControlRuleCategory

    def evaluate(
        self,
        context: QualityControlContext,
        thresholds: QualityControlThresholdConfig,
    ) -> list[PendingIssue]:
        raise NotImplementedError


class FunctionalQualityControlRule(QualityControlRule):
    def __init__(
        self,
        *,
        rule_id: str,
        rule_version: str,
        category: QualityControlRuleCategory,
        evaluator: Callable[
            [QualityControlContext, QualityControlThresholdConfig], list[PendingIssue]
        ],
    ) -> None:
        self.rule_id = rule_id
        self.rule_version = rule_version
        self.category = category
        self._evaluator = evaluator

    def evaluate(
        self,
        context: QualityControlContext,
        thresholds: QualityControlThresholdConfig,
    ) -> list[PendingIssue]:
        return self._evaluator(context, thresholds)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _round_float(value: float) -> float:
    return round(value, 6)


def _normalized_fingerprint_value(value: Any) -> Any:
    if isinstance(value, float):
        return _round_float(value)
    if isinstance(value, list):
        return [_normalized_fingerprint_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalized_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _fingerprint(rule_id: str, payload: dict[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "rule_id": rule_id,
            "payload": _normalized_fingerprint_value(payload),
        }
    )


def _issue(
    *,
    rule: QualityControlRule,
    severity: QualityControlSeverity,
    title: str,
    explanation: str,
    project_id: str,
    dataset_version_id: str | None,
    image_id: str | None,
    annotation_ids: list[str] | None = None,
    prediction_ids: list[str] | None = None,
    class_ids: list[str] | None = None,
    measured_values: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    fingerprint_payload: dict[str, Any] | None = None,
) -> PendingIssue:
    annotation_ids = sorted(annotation_ids or [])
    prediction_ids = sorted(prediction_ids or [])
    class_ids = sorted(class_ids or [])
    measured_values = measured_values or {}
    thresholds = thresholds or {}
    payload = fingerprint_payload or {
        "dataset_version_id": dataset_version_id,
        "image_id": image_id,
        "annotation_ids": annotation_ids,
        "prediction_ids": prediction_ids,
        "class_ids": class_ids,
        "measured_values": measured_values,
    }
    return PendingIssue(
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        severity=severity,
        title=title,
        explanation=explanation,
        project_id=project_id,
        dataset_version_id=dataset_version_id,
        image_id=image_id,
        annotation_ids=annotation_ids,
        prediction_ids=prediction_ids,
        class_ids=class_ids,
        measured_values=measured_values,
        thresholds=thresholds,
        fingerprint_payload=payload,
    )


def _bbox_width(annotation: EvaluatedAnnotation) -> float:
    return annotation.x_max - annotation.x_min


def _bbox_height(annotation: EvaluatedAnnotation) -> float:
    return annotation.y_max - annotation.y_min


def _bbox_iou(left: EvaluatedAnnotation, right: EvaluatedAnnotation) -> float:
    inter_left = max(left.x_min, right.x_min)
    inter_top = max(left.y_min, right.y_min)
    inter_right = min(left.x_max, right.x_max)
    inter_bottom = min(left.y_max, right.y_max)
    inter_width = max(0.0, inter_right - inter_left)
    inter_height = max(0.0, inter_bottom - inter_top)
    intersection = inter_width * inter_height
    if intersection <= 0:
        return 0.0
    left_area = max(0.0, _bbox_width(left)) * max(0.0, _bbox_height(left))
    right_area = max(0.0, _bbox_width(right)) * max(0.0, _bbox_height(right))
    union = left_area + right_area - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _candidate_pairs(
    annotations: list[EvaluatedAnnotation],
    cell_size: int,
) -> list[tuple[EvaluatedAnnotation, EvaluatedAnnotation]]:
    grid: dict[tuple[int, int], list[EvaluatedAnnotation]] = defaultdict(list)
    pairs: list[tuple[EvaluatedAnnotation, EvaluatedAnnotation]] = []
    seen: set[tuple[str, str]] = set()
    ordered = sorted(annotations, key=lambda item: (item.x_min, item.y_min, item.id))
    for annotation in ordered:
        x_start = floor(annotation.x_min / cell_size)
        x_end = floor(max(annotation.x_max - 1, annotation.x_min) / cell_size)
        y_start = floor(annotation.y_min / cell_size)
        y_end = floor(max(annotation.y_max - 1, annotation.y_min) / cell_size)
        for cell_x in range(x_start, x_end + 1):
            for cell_y in range(y_start, y_end + 1):
                cell = (cell_x, cell_y)
                for other in grid[cell]:
                    pair = (
                        annotation.id if annotation.id < other.id else other.id,
                        other.id if annotation.id < other.id else annotation.id,
                    )
                    if pair in seen:
                        continue
                    seen.add(pair)
                    pairs.append((annotation, other))
                grid[cell].append(annotation)
    return pairs


def _split_bucket(
    timestamp: datetime,
    *,
    window_minutes: int,
) -> datetime:
    normalized = timestamp.astimezone(UTC)
    rounded_minutes = normalized.minute - (normalized.minute % window_minutes)
    return normalized.replace(minute=rounded_minutes, second=0, microsecond=0)


def _manifest_consistency_errors(
    version: DatasetVersion,
    items: list[DatasetVersionItem],
) -> list[str]:
    problems: list[str] = []
    if canonical_json_sha256(version.manifest_json) != version.manifest_sha256:
        problems.append("Stored manifest checksum does not match the canonical manifest payload.")
    manifest_items = version.manifest_json.get("items")
    if not isinstance(manifest_items, list):
        problems.append("Manifest items are missing or not a list.")
        return problems
    if len(manifest_items) != len(items):
        problems.append("Manifest item count does not match persisted dataset-version items.")
    manifest_by_image_id: dict[str, dict[str, Any]] = {}
    for item in manifest_items:
        if isinstance(item, dict) and isinstance(item.get("image_id"), str):
            manifest_by_image_id[str(item["image_id"])] = cast(dict[str, Any], item)
    for item in items:
        manifest_item = manifest_by_image_id.get(item.image_id)
        if manifest_item is None:
            problems.append(f"Manifest is missing image {item.image_id}.")
            continue
        if manifest_item.get("snapshot_sha256") != item.snapshot_sha256:
            problems.append(f"Snapshot checksum mismatch for image {item.image_id}.")
        if manifest_item.get("split") != item.split:
            problems.append(f"Split mismatch for image {item.image_id}.")
        if int(manifest_item.get("annotation_count", -1)) != item.annotation_count:
            problems.append(f"Annotation count mismatch for image {item.image_id}.")
    summary = version.manifest_json.get("summary")
    if not isinstance(summary, dict):
        problems.append("Manifest summary section is missing.")
    else:
        if int(summary.get("image_count", -1)) != version.image_count:
            problems.append("Manifest summary image count does not match the version record.")
        if int(summary.get("annotation_count", -1)) != version.annotation_count:
            problems.append("Manifest summary annotation count does not match the version record.")
    return problems


def _evaluate_invalid_boxes(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["invalid_bounding_box"]
    issues: list[PendingIssue] = []
    for annotation in context.annotations:
        if (
            not all(
                isfinite(value)
                for value in (
                    annotation.x_min,
                    annotation.y_min,
                    annotation.x_max,
                    annotation.y_max,
                )
            )
            or annotation.x_max < annotation.x_min
            or annotation.y_max < annotation.y_min
        ):
            issues.append(
                _issue(
                    rule=rule,
                    severity="error",
                    title="Invalid bounding box",
                    explanation=(
                        "The annotation has non-finite coordinates or an inverted box edge."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=context.dataset_version.id
                    if context.dataset_version is not None
                    else None,
                    image_id=annotation.image_id,
                    annotation_ids=[annotation.id],
                    class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
                    measured_values={
                        "x_min": annotation.x_min,
                        "y_min": annotation.y_min,
                        "x_max": annotation.x_max,
                        "y_max": annotation.y_max,
                    },
                )
            )
    return issues


def _evaluate_zero_area_boxes(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["zero_area_box"]
    issues: list[PendingIssue] = []
    for annotation in context.annotations:
        width = _bbox_width(annotation)
        height = _bbox_height(annotation)
        if width == 0 or height == 0:
            issues.append(
                _issue(
                    rule=rule,
                    severity="error",
                    title="Zero-area bounding box",
                    explanation=(
                        "The annotation has zero width or zero height in source-image pixels."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=context.dataset_version.id
                    if context.dataset_version is not None
                    else None,
                    image_id=annotation.image_id,
                    annotation_ids=[annotation.id],
                    class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
                    measured_values={"width_px": width, "height_px": height},
                )
            )
    return issues


def _evaluate_small_boxes(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["small_box"]
    issues: list[PendingIssue] = []
    for annotation in context.annotations:
        width = _bbox_width(annotation)
        height = _bbox_height(annotation)
        if width <= 0 or height <= 0:
            continue
        if width < thresholds.small_box_min_width_px or height < thresholds.small_box_min_height_px:
            issues.append(
                _issue(
                    rule=rule,
                    severity="warning",
                    title="Extremely small bounding box",
                    explanation=(
                        "This annotation is very small in source-image pixels "
                        "and may be hard to verify."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=context.dataset_version.id
                    if context.dataset_version is not None
                    else None,
                    image_id=annotation.image_id,
                    annotation_ids=[annotation.id],
                    class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
                    measured_values={"width_px": width, "height_px": height},
                    thresholds={
                        "small_box_min_width_px": thresholds.small_box_min_width_px,
                        "small_box_min_height_px": thresholds.small_box_min_height_px,
                    },
                )
            )
    return issues


def _evaluate_out_of_bounds_boxes(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["out_of_bounds_box"]
    issues: list[PendingIssue] = []
    for annotation in context.annotations:
        image = context.images_by_id.get(annotation.image_id)
        if image is None:
            continue
        if (
            annotation.x_min < 0
            or annotation.y_min < 0
            or annotation.x_max > image.width_px
            or annotation.y_max > image.height_px
        ):
            issues.append(
                _issue(
                    rule=rule,
                    severity="error",
                    title="Out-of-bounds bounding box",
                    explanation="The annotation extends outside the source-image boundaries.",
                    project_id=context.project.id,
                    dataset_version_id=context.dataset_version.id
                    if context.dataset_version is not None
                    else None,
                    image_id=annotation.image_id,
                    annotation_ids=[annotation.id],
                    class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
                    measured_values={
                        "x_min": annotation.x_min,
                        "y_min": annotation.y_min,
                        "x_max": annotation.x_max,
                        "y_max": annotation.y_max,
                        "image_width_px": image.width_px,
                        "image_height_px": image.height_px,
                    },
                )
            )
    return issues


def _evaluate_boundary_touching_boxes(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["boundary_touching_box"]
    issues: list[PendingIssue] = []
    margin = thresholds.boundary_touch_margin_px
    for annotation in context.annotations:
        image = context.images_by_id.get(annotation.image_id)
        if image is None:
            continue
        touches = (
            annotation.x_min <= margin
            or annotation.y_min <= margin
            or annotation.x_max >= image.width_px - margin
            or annotation.y_max >= image.height_px - margin
        )
        if touches:
            issues.append(
                _issue(
                    rule=rule,
                    severity="info",
                    title="Boundary-touching bounding box",
                    explanation=(
                        "The annotation touches the image boundary, which can "
                        "be a valid edge case but merits review."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=context.dataset_version.id
                    if context.dataset_version is not None
                    else None,
                    image_id=annotation.image_id,
                    annotation_ids=[annotation.id],
                    class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
                    measured_values={
                        "image_width_px": image.width_px,
                        "image_height_px": image.height_px,
                        "x_min": annotation.x_min,
                        "y_min": annotation.y_min,
                        "x_max": annotation.x_max,
                        "y_max": annotation.y_max,
                    },
                    thresholds={"boundary_touch_margin_px": margin},
                )
            )
    return issues


def _evaluate_exact_duplicates(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["exact_duplicate_box"]
    geometry_groups: dict[tuple[str, float, float, float, float], list[EvaluatedAnnotation]] = (
        defaultdict(list)
    )
    for annotation in context.annotations:
        geometry_groups[
            (
                annotation.image_id,
                _round_float(annotation.x_min),
                _round_float(annotation.y_min),
                _round_float(annotation.x_max),
                _round_float(annotation.y_max),
            )
        ].append(annotation)
    issues: list[PendingIssue] = []
    for duplicate_group in geometry_groups.values():
        if len(duplicate_group) < 2:
            continue
        class_ids = sorted(
            {
                annotation.label_class_id
                for annotation in duplicate_group
                if annotation.label_class_id
            }
        )
        severity: QualityControlSeverity = "error" if len(class_ids) <= 1 else "warning"
        issues.append(
            _issue(
                rule=rule,
                severity=severity,
                title="Exact duplicate boxes",
                explanation="Multiple annotations share identical coordinates on the same image.",
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=duplicate_group[0].image_id,
                annotation_ids=[annotation.id for annotation in duplicate_group],
                class_ids=class_ids,
                measured_values={
                    "duplicate_count": len(duplicate_group),
                    "class_count": len(class_ids),
                },
            )
        )
    return issues


def _evaluate_near_duplicates(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["near_duplicate_box"]
    issues: list[PendingIssue] = []
    for image_id, image_annotations in context.annotations_by_image.items():
        for left, right in _candidate_pairs(image_annotations, thresholds.overlap_spatial_cell_px):
            if left.label_class_id is None or left.label_class_id != right.label_class_id:
                continue
            iou = _bbox_iou(left, right)
            if iou >= 1.0 or iou < thresholds.near_duplicate_iou_threshold:
                continue
            issues.append(
                _issue(
                    rule=rule,
                    severity="warning",
                    title="Near-duplicate boxes",
                    explanation=(
                        "Two same-class annotations are almost identical at "
                        "the configured IoU threshold."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=(
                        context.dataset_version.id if context.dataset_version else None
                    ),
                    image_id=image_id,
                    annotation_ids=[left.id, right.id],
                    class_ids=[left.label_class_id],
                    measured_values={"iou": iou},
                    thresholds={
                        "near_duplicate_iou_threshold": thresholds.near_duplicate_iou_threshold
                    },
                )
            )
    return issues


def _evaluate_same_class_overlap(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["same_class_overlap"]
    issues: list[PendingIssue] = []
    for image_id, image_annotations in context.annotations_by_image.items():
        for left, right in _candidate_pairs(image_annotations, thresholds.overlap_spatial_cell_px):
            if left.label_class_id is None or left.label_class_id != right.label_class_id:
                continue
            iou = _bbox_iou(left, right)
            if (
                iou < thresholds.same_class_overlap_iou_threshold
                or iou >= thresholds.near_duplicate_iou_threshold
            ):
                continue
            issues.append(
                _issue(
                    rule=rule,
                    severity="warning",
                    title="Excessive same-class overlap",
                    explanation=(
                        "Two same-class annotations overlap heavily and may "
                        "represent duplicate labeling."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=(
                        context.dataset_version.id if context.dataset_version else None
                    ),
                    image_id=image_id,
                    annotation_ids=[left.id, right.id],
                    class_ids=[left.label_class_id],
                    measured_values={"iou": iou},
                    thresholds={
                        "same_class_overlap_iou_threshold": (
                            thresholds.same_class_overlap_iou_threshold
                        )
                    },
                )
            )
    return issues


def _evaluate_different_class_overlap(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["different_class_overlap"]
    issues: list[PendingIssue] = []
    for image_id, image_annotations in context.annotations_by_image.items():
        for left, right in _candidate_pairs(image_annotations, thresholds.overlap_spatial_cell_px):
            if left.label_class_id is None or left.label_class_id == right.label_class_id:
                continue
            iou = _bbox_iou(left, right)
            if iou < thresholds.different_class_overlap_iou_threshold:
                continue
            issues.append(
                _issue(
                    rule=rule,
                    severity="warning",
                    title="Excessive different-class overlap",
                    explanation=(
                        "Different-class annotations overlap heavily. This can "
                        "be valid, but it often deserves review."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=(
                        context.dataset_version.id if context.dataset_version else None
                    ),
                    image_id=image_id,
                    annotation_ids=[left.id, right.id],
                    class_ids=sorted(
                        [item for item in (left.label_class_id, right.label_class_id) if item]
                    ),
                    measured_values={"iou": iou},
                    thresholds={
                        "different_class_overlap_iou_threshold": (
                            thresholds.different_class_overlap_iou_threshold
                        )
                    },
                )
            )
    return issues


def _evaluate_missing_classes(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["missing_or_invalid_class"]
    issues: list[PendingIssue] = []
    for annotation in context.annotations:
        if annotation.label_class_id and annotation.label_class_id in context.label_classes_by_id:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="error",
                title="Annotation references an unavailable class",
                explanation=(
                    "The annotation points to a class that is missing from the "
                    "current project class map."
                ),
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=annotation.image_id,
                annotation_ids=[annotation.id],
                class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
                measured_values={"label_class_id": annotation.label_class_id},
            )
        )
    return issues


def _evaluate_unavailable_images(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["annotation_unavailable_image"]
    issues: list[PendingIssue] = []
    for annotation in context.annotations:
        if annotation.image_id in context.images_by_id:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="error",
                title="Annotation references an unavailable image",
                explanation=(
                    "The annotation points to an image that is not available "
                    "in the selected QC scope."
                ),
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=annotation.image_id,
                annotation_ids=[annotation.id],
                class_ids=[annotation.label_class_id] if annotation.label_class_id else [],
            )
        )
    return issues


def _evaluate_reviewed_without_annotations(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["reviewed_without_annotations"]
    issues: list[PendingIssue] = []
    for image in context.images:
        if image.annotation_status != "reviewed":
            continue
        if context.annotations_by_image.get(image.image_id):
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="warning",
                title="Reviewed image has zero annotations",
                explanation=(
                    "The image is marked reviewed but no verified annotations "
                    "were found in the selected scope."
                ),
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=image.image_id,
                measured_values={"annotation_status": image.annotation_status},
            )
        )
    return issues


def _evaluate_annotation_count_outliers(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["annotation_count_outlier"]
    counts = [len(context.annotations_by_image.get(image.image_id, [])) for image in context.images]
    if not counts:
        return []
    center = float(median(counts))
    deviations = [abs(count - center) for count in counts]
    mad = float(median(deviations))
    scale = mad if mad > 0 else 1.0
    issues: list[PendingIssue] = []
    for image in context.images:
        count = len(context.annotations_by_image.get(image.image_id, []))
        score = (count - center) / scale
        if score >= thresholds.annotation_count_mad_multiplier:
            direction = "high"
        elif score <= -thresholds.annotation_count_mad_multiplier:
            direction = "low"
        else:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="warning",
                title=f"Unusually {direction} annotation count",
                explanation=(
                    "The image-level annotation count is a deterministic MAD "
                    "outlier and should be reviewed as a heuristic warning."
                ),
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=image.image_id,
                measured_values={
                    "annotation_count": count,
                    "median": center,
                    "mad": mad,
                    "mad_score": score,
                    "direction": direction,
                },
                thresholds={
                    "annotation_count_mad_multiplier": (thresholds.annotation_count_mad_multiplier)
                },
            )
        )
    return issues


def _evaluate_class_imbalance(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["class_imbalance"]
    counts: Counter[str] = Counter()
    for annotation in context.annotations:
        if annotation.label_class_id in context.label_classes_by_id:
            counts[annotation.label_class_id] += 1
    total = sum(counts.values())
    if total <= 0:
        return []
    known_class_ids = sorted(context.label_classes_by_id)
    missing_class_ids = [class_id for class_id in known_class_ids if counts.get(class_id, 0) == 0]
    majority_class_id, majority_count = counts.most_common(1)[0]
    majority_fraction = majority_count / total
    if majority_fraction < thresholds.class_imbalance_majority_ratio and not missing_class_ids:
        return []
    issues = [
        _issue(
            rule=rule,
            severity="warning",
            title="Class imbalance warning",
            explanation=(
                "Class frequencies are skewed in the selected scope. This "
                "is a heuristic quality signal, not proof that any class "
                "is wrong."
            ),
            project_id=context.project.id,
            dataset_version_id=context.dataset_version.id if context.dataset_version else None,
            image_id=None,
            class_ids=known_class_ids,
            measured_values={
                "total_annotations": total,
                "counts_by_class_id": dict(counts),
                "missing_class_ids": missing_class_ids,
                "majority_class_id": majority_class_id,
                "majority_fraction": majority_fraction,
            },
            thresholds={
                "class_imbalance_majority_ratio": (thresholds.class_imbalance_majority_ratio)
            },
            fingerprint_payload={
                "dataset_version_id": (
                    context.dataset_version.id if context.dataset_version else None
                ),
                "counts_by_class_id": dict(counts),
                "missing_class_ids": missing_class_ids,
            },
        )
    ]
    return issues


def _evaluate_missing_group_keys(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["missing_group_key"]
    issues: list[PendingIssue] = []
    for image in context.images:
        if image.group_key is not None and image.group_key.strip():
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="info",
                title="Missing group key",
                explanation=(
                    "The image has no group key. Group-aware splits and grouped "
                    "review workflows may be less reliable."
                ),
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=image.image_id,
            )
        )
    return issues


def _evaluate_unmapped_predictions(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["prediction_unmapped_class"]
    issues: list[PendingIssue] = []
    for prediction in context.predictions:
        if prediction.label_class_id is not None:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="warning",
                title="Prediction has no mapped project class",
                explanation=(
                    "The prediction proposal is unmapped and cannot be accepted "
                    "without an explicit class choice."
                ),
                project_id=context.project.id,
                dataset_version_id=None,
                image_id=prediction.image_id,
                prediction_ids=[prediction.id],
                measured_values={"predicted_label": prediction.predicted_label},
            )
        )
    return issues


def _evaluate_missing_prediction_provenance(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["accepted_prediction_missing_provenance"]
    annotations_by_source_prediction: dict[str, EvaluatedAnnotation] = {
        annotation.source_prediction_id: annotation
        for annotation in context.annotations
        if annotation.source_prediction_id is not None
    }
    issues: list[PendingIssue] = []
    for prediction in context.predictions:
        if prediction.review_status not in {"accepted", "edited_and_accepted"}:
            continue
        annotation = (
            annotations_by_source_prediction.get(prediction.id)
            if prediction.accepted_annotation_id is None
            else next(
                (
                    item
                    for item in context.annotations
                    if item.id == prediction.accepted_annotation_id
                ),
                None,
            )
        )
        proposal_missing = not prediction.provenance_json
        annotation_missing = annotation is not None and not annotation.provenance_json
        if not proposal_missing and not annotation_missing:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="warning",
                title="Accepted prediction is missing provenance",
                explanation=(
                    "A reviewed prediction or its accepted annotation is "
                    "missing provenance metadata."
                ),
                project_id=context.project.id,
                dataset_version_id=None,
                image_id=prediction.image_id,
                annotation_ids=[annotation.id] if annotation is not None else [],
                prediction_ids=[prediction.id],
                class_ids=[annotation.label_class_id]
                if annotation and annotation.label_class_id
                else [],
                measured_values={
                    "proposal_provenance_present": not proposal_missing,
                    "annotation_provenance_present": not annotation_missing,
                },
            )
        )
    return issues


def _evaluate_bulk_acceptance(
    context: QualityControlContext,
    thresholds: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["suspicious_bulk_acceptance"]
    grouped: dict[tuple[str, datetime], list[EvaluatedPrediction]] = defaultdict(list)
    for prediction in context.predictions:
        if (
            prediction.review_status not in {"accepted", "edited_and_accepted"}
            or prediction.reviewer_action_at is None
        ):
            continue
        bucket = _split_bucket(
            prediction.reviewer_action_at,
            window_minutes=thresholds.suspicious_bulk_acceptance_window_minutes,
        )
        grouped[(prediction.model_id, bucket)].append(prediction)
    issues: list[PendingIssue] = []
    for (model_id, bucket), predictions in grouped.items():
        if len(predictions) < thresholds.suspicious_bulk_acceptance_min_count:
            continue
        edited_fraction = sum(1 for item in predictions if item.was_edited) / len(predictions)
        if edited_fraction > 0.25:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="warning",
                title="Suspicious model-assisted bulk acceptance",
                explanation=(
                    "A large cluster of model proposals was accepted in a "
                    "short window with very few edits. This is a heuristic "
                    "warning only."
                ),
                project_id=context.project.id,
                dataset_version_id=None,
                image_id=None,
                prediction_ids=[item.id for item in predictions],
                measured_values={
                    "model_id": model_id,
                    "accepted_count": len(predictions),
                    "edited_fraction": edited_fraction,
                    "time_bucket_utc": bucket.isoformat(),
                },
                thresholds={
                    "suspicious_bulk_acceptance_min_count": (
                        thresholds.suspicious_bulk_acceptance_min_count
                    ),
                    "suspicious_bulk_acceptance_window_minutes": (
                        thresholds.suspicious_bulk_acceptance_window_minutes
                    ),
                },
                fingerprint_payload={
                    "model_id": model_id,
                    "time_bucket_utc": bucket.isoformat(),
                    "prediction_ids": sorted(item.id for item in predictions),
                },
            )
        )
    return issues


def _evaluate_manifest_inconsistencies(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["dataset_manifest_inconsistency"]
    issues: list[PendingIssue] = []
    for version in context.dataset_versions:
        if version.status != "complete":
            continue
        items = context.dataset_version_items_by_version.get(version.id, [])
        problems = _manifest_consistency_errors(version, items)
        if not problems:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="error",
                title="Dataset-version manifest inconsistency",
                explanation=(
                    "The dataset-version manifest does not match the persisted immutable snapshot."
                ),
                project_id=context.project.id,
                dataset_version_id=version.id,
                image_id=None,
                measured_values={
                    "problem_count": len(problems),
                    "problems": problems,
                    "manifest_sha256": version.manifest_sha256,
                },
                fingerprint_payload={"dataset_version_id": version.id, "problems": problems},
            )
        )
    return issues


def _evaluate_missing_checksums(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["missing_image_checksum"]
    issues: list[PendingIssue] = []
    for image in context.images:
        if image.sha256:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="error",
                title="Missing image checksum",
                explanation="The image record is missing its stored checksum.",
                project_id=context.project.id,
                dataset_version_id=context.dataset_version.id if context.dataset_version else None,
                image_id=image.image_id,
            )
        )
    for version_id, items in context.dataset_version_items_by_version.items():
        for item in items:
            if item.image_sha256:
                continue
            issues.append(
                _issue(
                    rule=rule,
                    severity="error",
                    title="Dataset-version item is missing an image checksum",
                    explanation=(
                        "The immutable dataset-version item is missing its frozen image checksum."
                    ),
                    project_id=context.project.id,
                    dataset_version_id=version_id,
                    image_id=item.image_id,
                )
            )
    return issues


def _evaluate_broken_managed_files(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["broken_managed_file_reference"]
    issues: list[PendingIssue] = []
    for image in context.images:
        if image.managed_path:
            managed_path = resolve_managed_project_path(context.settings, image.managed_path)
            if not managed_path.is_file():
                issues.append(
                    _issue(
                        rule=rule,
                        severity="error",
                        title="Broken managed image reference",
                        explanation=(
                            "The stored managed image path does not point to an existing file."
                        ),
                        project_id=context.project.id,
                        dataset_version_id=context.dataset_version.id
                        if context.dataset_version
                        else None,
                        image_id=image.image_id,
                        measured_values={"managed_path": image.managed_path},
                    )
                )
        if image.thumbnail_path:
            thumbnail_path = resolve_managed_project_path(context.settings, image.thumbnail_path)
            if not thumbnail_path.is_file():
                issues.append(
                    _issue(
                        rule=rule,
                        severity="warning",
                        title="Broken thumbnail reference",
                        explanation="The stored thumbnail path does not point to an existing file.",
                        project_id=context.project.id,
                        dataset_version_id=context.dataset_version.id
                        if context.dataset_version
                        else None,
                        image_id=image.image_id,
                        measured_values={"thumbnail_path": image.thumbnail_path},
                        fingerprint_payload={
                            "image_id": image.image_id,
                            "thumbnail_path": image.thumbnail_path,
                        },
                    )
                )
    return issues


def _evaluate_inconsistent_split_metadata(
    context: QualityControlContext,
    _: QualityControlThresholdConfig,
) -> list[PendingIssue]:
    rule = RULES_BY_ID["inconsistent_split_metadata"]
    issues: list[PendingIssue] = []
    for version in context.dataset_versions:
        if version.status != "complete":
            continue
        items = context.dataset_version_items_by_version.get(version.id, [])
        invalid_splits = sorted({item.split for item in items if item.split not in ALLOWED_SPLITS})
        grouped_splits: dict[str, set[str]] = defaultdict(set)
        for item in items:
            if item.group_key:
                grouped_splits[item.group_key].add(item.split)
        conflicting_groups = sorted(
            group_key for group_key, splits in grouped_splits.items() if len(splits) > 1
        )
        if not invalid_splits and not conflicting_groups:
            continue
        issues.append(
            _issue(
                rule=rule,
                severity="error",
                title="Inconsistent split metadata",
                explanation=(
                    "The immutable dataset snapshot contains invalid split "
                    "labels or a group key assigned to multiple splits."
                ),
                project_id=context.project.id,
                dataset_version_id=version.id,
                image_id=None,
                measured_values={
                    "invalid_splits": invalid_splits,
                    "conflicting_groups": conflicting_groups,
                },
            )
        )
    return issues


RULE_REGISTRY: tuple[QualityControlRule, ...] = (
    FunctionalQualityControlRule(
        rule_id="invalid_bounding_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_invalid_boxes,
    ),
    FunctionalQualityControlRule(
        rule_id="zero_area_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_zero_area_boxes,
    ),
    FunctionalQualityControlRule(
        rule_id="small_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_small_boxes,
    ),
    FunctionalQualityControlRule(
        rule_id="out_of_bounds_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_out_of_bounds_boxes,
    ),
    FunctionalQualityControlRule(
        rule_id="boundary_touching_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_boundary_touching_boxes,
    ),
    FunctionalQualityControlRule(
        rule_id="exact_duplicate_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_exact_duplicates,
    ),
    FunctionalQualityControlRule(
        rule_id="near_duplicate_box",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_near_duplicates,
    ),
    FunctionalQualityControlRule(
        rule_id="same_class_overlap",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_same_class_overlap,
    ),
    FunctionalQualityControlRule(
        rule_id="different_class_overlap",
        rule_version="1.0.0",
        category="annotation_geometry",
        evaluator=_evaluate_different_class_overlap,
    ),
    FunctionalQualityControlRule(
        rule_id="missing_or_invalid_class",
        rule_version="1.0.0",
        category="annotation_semantics",
        evaluator=_evaluate_missing_classes,
    ),
    FunctionalQualityControlRule(
        rule_id="annotation_unavailable_image",
        rule_version="1.0.0",
        category="annotation_semantics",
        evaluator=_evaluate_unavailable_images,
    ),
    FunctionalQualityControlRule(
        rule_id="reviewed_without_annotations",
        rule_version="1.0.0",
        category="annotation_semantics",
        evaluator=_evaluate_reviewed_without_annotations,
    ),
    FunctionalQualityControlRule(
        rule_id="annotation_count_outlier",
        rule_version="1.0.0",
        category="statistics",
        evaluator=_evaluate_annotation_count_outliers,
    ),
    FunctionalQualityControlRule(
        rule_id="class_imbalance",
        rule_version="1.0.0",
        category="statistics",
        evaluator=_evaluate_class_imbalance,
    ),
    FunctionalQualityControlRule(
        rule_id="missing_group_key",
        rule_version="1.0.0",
        category="statistics",
        evaluator=_evaluate_missing_group_keys,
    ),
    FunctionalQualityControlRule(
        rule_id="prediction_unmapped_class",
        rule_version="1.0.0",
        category="predictions",
        evaluator=_evaluate_unmapped_predictions,
    ),
    FunctionalQualityControlRule(
        rule_id="accepted_prediction_missing_provenance",
        rule_version="1.0.0",
        category="predictions",
        evaluator=_evaluate_missing_prediction_provenance,
    ),
    FunctionalQualityControlRule(
        rule_id="suspicious_bulk_acceptance",
        rule_version="1.0.0",
        category="predictions",
        evaluator=_evaluate_bulk_acceptance,
    ),
    FunctionalQualityControlRule(
        rule_id="dataset_manifest_inconsistency",
        rule_version="1.0.0",
        category="dataset_versions",
        evaluator=_evaluate_manifest_inconsistencies,
    ),
    FunctionalQualityControlRule(
        rule_id="inconsistent_split_metadata",
        rule_version="1.0.0",
        category="dataset_versions",
        evaluator=_evaluate_inconsistent_split_metadata,
    ),
    FunctionalQualityControlRule(
        rule_id="missing_image_checksum",
        rule_version="1.0.0",
        category="image_integrity",
        evaluator=_evaluate_missing_checksums,
    ),
    FunctionalQualityControlRule(
        rule_id="broken_managed_file_reference",
        rule_version="1.0.0",
        category="image_integrity",
        evaluator=_evaluate_broken_managed_files,
    ),
)
RULES_BY_ID: dict[str, QualityControlRule] = {rule.rule_id: rule for rule in RULE_REGISTRY}


class QualityControlService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.versions = DatasetVersionRepository(session)
        self.jobs = JobRepository(session)
        self.quality_control = QualityControlRepository(session)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _run(self, run_id: str) -> QualityControlRun:
        run = self.quality_control.get_run(run_id)
        if run is None:
            raise NotFoundError("Quality-control run not found")
        return run

    def _version(self, version_id: str) -> DatasetVersion:
        version = self.versions.get_version(version_id)
        if version is None:
            raise NotFoundError("Dataset version not found")
        return version

    def _issue_row(self, issue_id: str) -> QualityControlIssue:
        issue = self.quality_control.get_issue(issue_id)
        if issue is None:
            raise NotFoundError("Quality-control issue not found")
        return issue

    def _selected_rules(self, request: QualityControlRunCreateRequest) -> list[QualityControlRule]:
        categories = set(request.rule_categories or QUALITY_CONTROL_RULE_CATEGORIES)
        selected = [rule for rule in RULE_REGISTRY if rule.category in categories]
        if request.selected_rule_ids:
            requested_ids = set(request.selected_rule_ids)
            selected = [rule for rule in selected if rule.rule_id in requested_ids]
        if not selected:
            raise ValidationError("Choose at least one applicable quality-control rule")
        return selected

    def _queue_run(
        self,
        *,
        project: Project,
        dataset_version: DatasetVersion | None,
        request: QualityControlRunCreateRequest,
    ) -> QualityControlRun:
        rules = self._selected_rules(request)
        run = QualityControlRun(
            project_id=project.id,
            dataset_version_id=dataset_version.id if dataset_version else None,
            scope_type="dataset_version" if dataset_version else "project",
            status="queued",
            rule_categories_json=list(request.rule_categories or QUALITY_CONTROL_RULE_CATEGORIES),
            selected_rule_ids_json=[rule.rule_id for rule in rules],
            thresholds_json=request.thresholds.model_dump(mode="json"),
            configuration_json={
                "ruleset_version": CURRENT_QC_RULESET_VERSION,
                "scope_type": "dataset_version" if dataset_version else "project",
                "selected_rule_ids": [rule.rule_id for rule in rules],
                "rule_versions": {rule.rule_id: rule.rule_version for rule in rules},
            },
            input_checksums_json={},
            summary_json={},
            created_by=request.created_by or "local_user",
        )
        self.quality_control.add_run(run)
        self.session.flush()
        job = Job(
            project_id=project.id,
            job_type="qc",
            status="queued",
            progress_total=len(rules),
            request_json={"quality_control_run_id": run.id},
        )
        self.session.add(job)
        self.session.flush()
        run.job_id = job.id
        self.session.commit()
        self.session.refresh(run)
        return run

    def create_run_for_project(
        self,
        project_id: str,
        request: QualityControlRunCreateRequest,
    ) -> QualityControlRunResponse:
        project = self._project(project_id)
        return QualityControlRunResponse.model_validate(
            self._queue_run(project=project, dataset_version=None, request=request)
        )

    def create_run_for_dataset_version(
        self,
        version_id: str,
        request: QualityControlRunCreateRequest,
    ) -> QualityControlRunResponse:
        version = self._version(version_id)
        return QualityControlRunResponse.model_validate(
            self._queue_run(project=version.project, dataset_version=version, request=request)
        )

    def list_runs(
        self,
        project_id: str,
        *,
        dataset_version_id: str | None = None,
    ) -> list[QualityControlRunResponse]:
        self._project(project_id)
        return [
            QualityControlRunResponse.model_validate(item)
            for item in self.quality_control.list_runs(
                project_id, dataset_version_id=dataset_version_id
            )
        ]

    def get_run(self, run_id: str) -> QualityControlRunResponse:
        return QualityControlRunResponse.model_validate(self._run(run_id))

    def cancel_run(self, run_id: str) -> QualityControlRunResponse:
        run = self._run(run_id)
        job = self.jobs.get(run.job_id) if run.job_id else None
        if run.status == "queued":
            run.status = "cancelled"
            run.cancelled_at = _utc_now()
            if job is not None:
                job.status = "cancelled"
                job.completed_at = _utc_now()
        elif run.status == "running":
            run.status = "cancel_requested"
            if job is not None:
                job.status = "cancel_requested"
        else:
            raise ConflictError("Only queued or running quality-control runs can be cancelled")
        self.session.commit()
        self.session.refresh(run)
        return QualityControlRunResponse.model_validate(run)

    def acknowledge_issue(
        self,
        issue_id: str,
        request: QualityControlIssueAcknowledgeRequest,
    ) -> QualityControlIssueResponse:
        issue = self._issue_row(issue_id)
        if issue.status not in {"open", "acknowledged"}:
            raise ConflictError("Only open or acknowledged issues can be acknowledged")
        issue.status = "acknowledged"
        issue.acknowledged_at = _utc_now()
        issue.acknowledged_by = request.actor or "local_user"
        self.session.commit()
        self.session.refresh(issue)
        return QualityControlIssueResponse.model_validate(issue)

    def dismiss_issue(
        self,
        issue_id: str,
        request: QualityControlIssueDismissRequest,
    ) -> QualityControlIssueResponse:
        issue = self._issue_row(issue_id)
        if issue.status not in {"open", "acknowledged"}:
            raise ConflictError("Only open or acknowledged issues can be dismissed")
        issue.status = "dismissed"
        issue.dismissed_at = _utc_now()
        issue.dismissed_by = request.actor or "local_user"
        issue.dismissed_reason = request.reason
        issue.resolution_metadata_json = {
            **issue.resolution_metadata_json,
            "dismissed_reason": request.reason,
        }
        self.session.commit()
        self.session.refresh(issue)
        return QualityControlIssueResponse.model_validate(issue)

    def list_issues(
        self,
        run_id: str,
        *,
        page: int,
        page_size: int,
        severity: str | None,
        rule_id: str | None,
        class_id: str | None,
        image_id: str | None,
        status: str | None,
    ) -> QualityControlIssuePageResponse:
        self._run(run_id)
        items, total, pages = self.quality_control.paged_issues(
            run_id,
            page=page,
            page_size=page_size,
            severity=severity,
            rule_id=rule_id,
            class_id=class_id,
            image_id=image_id,
            status=status,
        )
        return QualityControlIssuePageResponse(
            items=[QualityControlIssueResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def compare_runs(self, run_id: str, other_run_id: str) -> QualityControlRunComparisonResponse:
        base = self._run(run_id)
        other = self._run(other_run_id)
        if base.project_id != other.project_id:
            raise ValidationError("Only runs from the same project can be compared")
        if base.dataset_version_id != other.dataset_version_id:
            raise ValidationError("Only runs from the same scope can be compared")
        base_by_fingerprint = {
            item.fingerprint: item for item in self.quality_control.issues_for_run(base.id)
        }
        other_by_fingerprint = {
            item.fingerprint: item for item in self.quality_control.issues_for_run(other.id)
        }
        added = [
            other_by_fingerprint[key]
            for key in sorted(set(other_by_fingerprint) - set(base_by_fingerprint))
        ]
        resolved = [
            base_by_fingerprint[key]
            for key in sorted(set(base_by_fingerprint) - set(other_by_fingerprint))
        ]
        unchanged_count = len(set(base_by_fingerprint) & set(other_by_fingerprint))
        return QualityControlRunComparisonResponse(
            base_run_id=base.id,
            compare_run_id=other.id,
            added_count=len(added),
            resolved_count=len(resolved),
            unchanged_count=unchanged_count,
            added=[
                QualityControlRunComparisonIssue(
                    fingerprint=item.fingerprint,
                    rule_id=item.rule_id,
                    severity=cast(QualityControlSeverity, item.severity),
                    title=item.title,
                    image_id=item.image_id,
                )
                for item in added
            ],
            resolved=[
                QualityControlRunComparisonIssue(
                    fingerprint=item.fingerprint,
                    rule_id=item.rule_id,
                    severity=cast(QualityControlSeverity, item.severity),
                    title=item.title,
                    image_id=item.image_id,
                )
                for item in resolved
            ],
        )

    def _check_cancelled(self, run_id: str) -> None:
        self.session.expire_all()
        run = self._run(run_id)
        job = self.jobs.get(run.job_id) if run.job_id else None
        if run.status == "cancel_requested" or (
            job is not None and job.status == "cancel_requested"
        ):
            raise ConflictError("Quality-control run was cancelled")

    def _project_annotations(self, project: Project) -> list[Annotation]:
        statement = (
            select(Annotation)
            .outerjoin(ImageAsset, ImageAsset.id == Annotation.image_id)
            .outerjoin(LabelClass, LabelClass.id == Annotation.label_class_id)
            .where(
                Annotation.deleted_at.is_(None),
                or_(ImageAsset.project_id == project.id, LabelClass.project_id == project.id),
            )
            .order_by(Annotation.image_id, Annotation.created_at, Annotation.id)
        )
        return list(self.session.scalars(statement))

    def _build_project_context(self, project: Project) -> QualityControlContext:
        image_statement = (
            select(ImageAsset)
            .where(ImageAsset.project_id == project.id)
            .order_by(ImageAsset.created_at, ImageAsset.id)
        )
        live_images = list(self.session.scalars(image_statement))
        live_images_by_id = {image.id: image for image in live_images}
        images = [
            EvaluatedImage(
                image_id=image.id,
                project_id=image.project_id,
                dataset_version_id=None,
                original_filename=image.original_filename,
                width_px=image.width_px,
                height_px=image.height_px,
                annotation_status=image.annotation_status,
                group_key=image.group_key,
                split=None,
                managed_path=image.managed_path,
                thumbnail_path=image.thumbnail_path,
                sha256=image.sha256,
                created_at=image.created_at,
                updated_at=image.updated_at,
            )
            for image in live_images
        ]
        annotations = [
            EvaluatedAnnotation(
                id=annotation.id,
                image_id=annotation.image_id,
                label_class_id=annotation.label_class_id,
                x_min=annotation.x_min,
                y_min=annotation.y_min,
                x_max=annotation.x_max,
                y_max=annotation.y_max,
                source_type=annotation.source_type,
                source_model_id=annotation.source_model_id,
                source_prediction_id=annotation.source_prediction_id,
                provenance_json=annotation.provenance_json,
                revision=annotation.revision,
            )
            for annotation in self._project_annotations(project)
        ]
        prediction_statement = (
            select(PredictionProposal)
            .where(PredictionProposal.project_id == project.id)
            .order_by(
                PredictionProposal.image_id,
                PredictionProposal.created_at,
                PredictionProposal.id,
            )
        )
        predictions = [
            EvaluatedPrediction(
                id=prediction.id,
                project_id=prediction.project_id,
                image_id=prediction.image_id,
                model_id=prediction.model_id,
                label_class_id=prediction.label_class_id,
                predicted_label=prediction.predicted_label,
                predicted_index=prediction.predicted_index,
                confidence=prediction.confidence,
                x_min=prediction.x_min,
                y_min=prediction.y_min,
                x_max=prediction.x_max,
                y_max=prediction.y_max,
                review_status=prediction.review_status,
                was_edited=prediction.was_edited,
                reviewer_action_at=prediction.reviewer_action_at,
                accepted_annotation_id=prediction.accepted_annotation_id,
                provenance_json=prediction.provenance_json,
                created_at=prediction.created_at,
            )
            for prediction in self.session.scalars(prediction_statement)
        ]
        version_statement = (
            select(DatasetVersion)
            .where(DatasetVersion.project_id == project.id)
            .order_by(DatasetVersion.created_at, DatasetVersion.id)
        )
        versions = list(self.session.scalars(version_statement))
        items_by_version = {
            version.id: self.versions.items_for_version(version.id) for version in versions
        }
        return self._context_from_parts(
            project=project,
            dataset_version=None,
            images=images,
            live_images_by_id=live_images_by_id,
            annotations=annotations,
            predictions=predictions,
            dataset_versions=versions,
            items_by_version=items_by_version,
        )

    def _build_dataset_version_context(self, version: DatasetVersion) -> QualityControlContext:
        items = self.versions.items_for_version(version.id)
        image_ids = sorted({item.image_id for item in items})
        image_statement = select(ImageAsset).where(ImageAsset.id.in_(image_ids))
        live_images = list(self.session.scalars(image_statement)) if image_ids else []
        live_images_by_id = {image.id: image for image in live_images}
        images: list[EvaluatedImage] = []
        for item in items:
            live_image = live_images_by_id.get(item.image_id)
            images.append(
                EvaluatedImage(
                    image_id=item.image_id,
                    project_id=version.project_id,
                    dataset_version_id=version.id,
                    original_filename=item.original_filename,
                    width_px=item.width_px,
                    height_px=item.height_px,
                    annotation_status=item.image_annotation_status,
                    group_key=item.group_key,
                    split=item.split,
                    managed_path=live_image.managed_path if live_image else None,
                    thumbnail_path=live_image.thumbnail_path if live_image else None,
                    sha256=item.image_sha256,
                    created_at=live_image.created_at if live_image else None,
                    updated_at=live_image.updated_at if live_image else None,
                )
            )
        annotations: list[EvaluatedAnnotation] = []
        for item in items:
            for snapshot in item.annotation_snapshot_json:
                annotation = snapshot
                annotations.append(
                    EvaluatedAnnotation(
                        id=str(annotation["id"]),
                        image_id=item.image_id,
                        label_class_id=cast(str | None, annotation.get("label_class_id")),
                        x_min=float(annotation["x_min"]),
                        y_min=float(annotation["y_min"]),
                        x_max=float(annotation["x_max"]),
                        y_max=float(annotation["y_max"]),
                        source_type=str(annotation.get("source_type") or "human"),
                        source_model_id=cast(str | None, annotation.get("source_model_id")),
                        source_prediction_id=cast(
                            str | None, annotation.get("source_prediction_id")
                        ),
                        provenance_json=cast(
                            dict[str, Any] | None, annotation.get("provenance_json")
                        ),
                        revision=int(annotation.get("revision", 1)),
                    )
                )
        return self._context_from_parts(
            project=version.project,
            dataset_version=version,
            images=images,
            live_images_by_id=live_images_by_id,
            annotations=annotations,
            predictions=[],
            dataset_versions=[version],
            items_by_version={version.id: items},
        )

    def _context_from_parts(
        self,
        *,
        project: Project,
        dataset_version: DatasetVersion | None,
        images: list[EvaluatedImage],
        live_images_by_id: dict[str, ImageAsset],
        annotations: list[EvaluatedAnnotation],
        predictions: list[EvaluatedPrediction],
        dataset_versions: list[DatasetVersion],
        items_by_version: dict[str, list[DatasetVersionItem]],
    ) -> QualityControlContext:
        images_by_id = {image.image_id: image for image in images}
        annotations_by_image: dict[str, list[EvaluatedAnnotation]] = defaultdict(list)
        for annotation in annotations:
            annotations_by_image[annotation.image_id].append(annotation)
        predictions_by_image: dict[str, list[EvaluatedPrediction]] = defaultdict(list)
        for prediction in predictions:
            predictions_by_image[prediction.image_id].append(prediction)
        label_classes_by_id = {label_class.id: label_class for label_class in project.label_classes}
        return QualityControlContext(
            project=project,
            settings=self.settings,
            scope_type="dataset_version" if dataset_version else "project",
            dataset_version=dataset_version,
            images=images,
            annotations=annotations,
            predictions=predictions,
            dataset_versions=dataset_versions,
            dataset_version_items_by_version=items_by_version,
            images_by_id=images_by_id,
            live_images_by_id=live_images_by_id,
            annotations_by_image=annotations_by_image,
            predictions_by_image=predictions_by_image,
            label_classes_by_id=label_classes_by_id,
        )

    def _build_input_checksums(self, context: QualityControlContext) -> dict[str, Any]:
        images_payload = [
            {
                "image_id": image.image_id,
                "sha256": image.sha256,
                "group_key": image.group_key,
                "annotation_status": image.annotation_status,
                "split": image.split,
                "managed_path": image.managed_path,
            }
            for image in sorted(context.images, key=lambda item: item.image_id)
        ]
        annotations_payload = [
            {
                "id": annotation.id,
                "image_id": annotation.image_id,
                "label_class_id": annotation.label_class_id,
                "x_min": annotation.x_min,
                "y_min": annotation.y_min,
                "x_max": annotation.x_max,
                "y_max": annotation.y_max,
                "source_type": annotation.source_type,
                "source_prediction_id": annotation.source_prediction_id,
                "source_model_id": annotation.source_model_id,
            }
            for annotation in sorted(context.annotations, key=lambda item: item.id)
        ]
        predictions_payload = [
            {
                "id": prediction.id,
                "image_id": prediction.image_id,
                "model_id": prediction.model_id,
                "label_class_id": prediction.label_class_id,
                "confidence": prediction.confidence,
                "review_status": prediction.review_status,
            }
            for prediction in sorted(context.predictions, key=lambda item: item.id)
        ]
        versions_payload = [
            {
                "id": version.id,
                "manifest_sha256": version.manifest_sha256,
                "image_count": version.image_count,
                "annotation_count": version.annotation_count,
                "status": version.status,
            }
            for version in sorted(context.dataset_versions, key=lambda item: item.id)
        ]
        payload = {
            "scope_type": context.scope_type,
            "dataset_version_id": context.dataset_version.id if context.dataset_version else None,
            "images": images_payload,
            "annotations": annotations_payload,
            "predictions": predictions_payload,
            "dataset_versions": versions_payload,
        }
        return {
            "scope_sha256": canonical_json_sha256(payload),
            "image_sha256": canonical_json_sha256(images_payload),
            "annotation_sha256": canonical_json_sha256(annotations_payload),
            "prediction_sha256": canonical_json_sha256(predictions_payload),
            "dataset_version_sha256": canonical_json_sha256(versions_payload),
            "image_count": len(images_payload),
            "annotation_count": len(annotations_payload),
            "prediction_count": len(predictions_payload),
            "dataset_version_count": len(versions_payload),
        }

    def _summarize_issues(self, issues: list[QualityControlIssue]) -> dict[str, Any]:
        severity_counts = Counter(issue.severity for issue in issues)
        rule_counts = Counter(issue.rule_id for issue in issues)
        return {
            "counts_by_severity": dict(severity_counts),
            "counts_by_rule": dict(rule_counts),
            "open_issue_count": len(issues),
        }

    def _apply_resolution_links(
        self,
        run: QualityControlRun,
        new_issues: list[QualityControlIssue],
    ) -> None:
        previous = self.quality_control.latest_complete_run(
            run.project_id,
            dataset_version_id=run.dataset_version_id,
            exclude_run_id=run.id,
        )
        if previous is None:
            return
        current_fingerprints = {issue.fingerprint for issue in new_issues}
        for issue in self.quality_control.issues_for_run(previous.id):
            if issue.status not in {"open", "acknowledged"}:
                continue
            if issue.fingerprint in current_fingerprints:
                continue
            issue.status = "resolved_in_later_run"
            issue.resolution_run_id = run.id
            issue.resolution_metadata_json = {
                **issue.resolution_metadata_json,
                "resolved_in_run_id": run.id,
            }

    def execute_run(self, run_id: str) -> QualityControlRun:
        run = self._run(run_id)
        if run.status not in {"queued", "running"}:
            raise ConflictError("Only queued or running quality-control runs can be executed")
        if run.dataset_version_id:
            context = self._build_dataset_version_context(self._version(run.dataset_version_id))
        else:
            context = self._build_project_context(self._project(run.project_id))
        thresholds = QualityControlThresholdConfig.model_validate(run.thresholds_json)
        selected_rules = [RULES_BY_ID[rule_id] for rule_id in run.selected_rule_ids_json]
        run.status = "running"
        run.started_at = run.started_at or _utc_now()
        run.input_checksums_json = self._build_input_checksums(context)
        job = self.jobs.get(run.job_id) if run.job_id else None
        if job is not None:
            job.status = "running"
            job.started_at = job.started_at or _utc_now()
            job.progress_total = len(selected_rules)
            job.progress_current = 0
            job.error_message = None
        self.session.commit()

        pending_issues: list[PendingIssue] = []
        try:
            for index, rule in enumerate(selected_rules, start=1):
                self._check_cancelled(run.id)
                pending_issues.extend(rule.evaluate(context, thresholds))
                if job is not None:
                    job.progress_current = index
                    self.session.commit()
        except ConflictError:
            run = self._run(run.id)
            if job is not None:
                job = self.jobs.get(job.id)
            run.status = "cancelled"
            run.cancelled_at = _utc_now()
            run.completed_at = None
            if job is not None:
                job.status = "cancelled"
                job.completed_at = _utc_now()
            self.session.commit()
            return run
        except Exception as exc:
            run = self._run(run.id)
            if job is not None:
                job = self.jobs.get(job.id)
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = _utc_now()
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = _utc_now()
            self.session.commit()
            raise

        issue_rows = [
            QualityControlIssue(
                quality_control_run_id=run.id,
                project_id=issue.project_id,
                dataset_version_id=issue.dataset_version_id,
                image_id=issue.image_id,
                rule_id=issue.rule_id,
                rule_version=issue.rule_version,
                severity=issue.severity,
                status="open",
                fingerprint=_fingerprint(issue.rule_id, issue.fingerprint_payload),
                title=issue.title,
                explanation=issue.explanation,
                annotation_ids_json=issue.annotation_ids,
                prediction_ids_json=issue.prediction_ids,
                class_ids_json=issue.class_ids,
                measured_values_json=issue.measured_values,
                thresholds_json=issue.thresholds,
                resolution_metadata_json={},
            )
            for issue in pending_issues
        ]
        self.quality_control.add_issues(issue_rows)
        run.issue_count = len(issue_rows)
        self._apply_resolution_links(run, issue_rows)
        run.summary_json = self._summarize_issues(issue_rows)
        run.status = "succeeded"
        run.completed_at = _utc_now()
        if job is not None:
            job.status = "succeeded"
            job.completed_at = _utc_now()
            job.progress_current = job.progress_total
            job.result_json = {
                "quality_control_run_id": run.id,
                "issue_count": len(issue_rows),
                "summary": run.summary_json,
            }
        self.session.commit()
        self.session.refresh(run)
        return run
