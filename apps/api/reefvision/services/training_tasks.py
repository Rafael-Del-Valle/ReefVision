"""Task-aware dataset checks for ReefVision training workflows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

DETECTION_TASK = "detect"
INSTANCE_SEGMENTATION_TASK = "segment"
SEMANTIC_SEGMENTATION_TASK = "semantic_segment"
SUPPORTED_ULTRALYTICS_TRAINING_TASKS = (
    DETECTION_TASK,
    INSTANCE_SEGMENTATION_TASK,
)
SUPPORTED_TRAINING_TASKS = (
    DETECTION_TASK,
    INSTANCE_SEGMENTATION_TASK,
    SEMANTIC_SEGMENTATION_TASK,
)


class TrainingDatasetItem(Protocol):
    """Minimum immutable dataset-item surface needed for task preflight."""

    split: str
    annotation_count: int
    mask_annotation_count: int
    mask_annotation_snapshot_json: list[dict[str, object]]


@dataclass(frozen=True)
class TaskDatasetPreflight:
    """Task-specific eligibility and transparency details for a dataset version."""

    task: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    box_count: int = 0
    polygon_count: int = 0
    raster_mask_count: int = 0
    polygon_counts_by_split: dict[str, int] = field(default_factory=dict)
    raster_counts_by_split: dict[str, int] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not self.blockers


def task_dataset_preflight(
    task: str,
    items: Iterable[TrainingDatasetItem],
) -> TaskDatasetPreflight:
    """Evaluate whether immutable items can feed the requested training task.

    Ultralytics instance-segmentation training consumes YOLO polygon labels. Frozen
    raster masks remain valid ReefVision annotations and semantic-training inputs,
    but they cannot be silently treated as YOLO polygons.
    """

    resolved_items = list(items)
    box_count = sum(max(item.annotation_count, 0) for item in resolved_items)
    polygon_counts_by_split: dict[str, int] = {}
    raster_counts_by_split: dict[str, int] = {}

    for item in resolved_items:
        split = str(item.split)
        for snapshot in item.mask_annotation_snapshot_json:
            geometry_kind = snapshot.get("geometry_kind")
            if geometry_kind == "polygon":
                polygon_counts_by_split[split] = polygon_counts_by_split.get(split, 0) + 1
            elif geometry_kind == "raster_mask":
                raster_counts_by_split[split] = raster_counts_by_split.get(split, 0) + 1

    polygon_count = sum(polygon_counts_by_split.values())
    raster_mask_count = sum(raster_counts_by_split.values())
    blockers: list[str] = []
    warnings: list[str] = []

    if task == DETECTION_TASK:
        if box_count <= 0:
            blockers.append("Object-detection training requires at least one bounding box")
    elif task == INSTANCE_SEGMENTATION_TASK:
        if polygon_count <= 0:
            blockers.append(
                "Ultralytics instance-segmentation training requires at least one polygon mask"
            )
        if polygon_counts_by_split.get("train", 0) <= 0:
            blockers.append(
                "The training split must contain at least one polygon mask for "
                "instance segmentation"
            )
        if polygon_counts_by_split.get("validation", 0) <= 0:
            warnings.append(
                "The validation split contains no polygon masks, so segmentation "
                "metrics may be unavailable"
            )
        if raster_mask_count > 0:
            warnings.append(
                f"{raster_mask_count} raster mask(s) will be excluded from YOLO "
                "polygon-segmentation training; use semantic-mask training or "
                "convert them to polygons"
            )
    elif task == SEMANTIC_SEGMENTATION_TASK:
        semantic_counts_by_split = {
            split: polygon_counts_by_split.get(split, 0) + raster_counts_by_split.get(split, 0)
            for split in set(polygon_counts_by_split) | set(raster_counts_by_split)
        }
        if polygon_count + raster_mask_count <= 0:
            blockers.append(
                "Semantic-segmentation training requires at least one polygon or raster mask"
            )
        if semantic_counts_by_split.get("train", 0) <= 0:
            blockers.append(
                "The training split must contain at least one polygon or raster mask for "
                "semantic segmentation"
            )
        if semantic_counts_by_split.get("validation", 0) <= 0:
            warnings.append(
                "The validation split contains no masks; ReefVision will create a "
                "deterministic holdout when at least two training images are available"
            )
        if polygon_count > 0 and raster_mask_count > 0:
            warnings.append(
                "Polygon and raster masks will be flattened into one indexed semantic "
                "label map using the dataset export overlap policy"
            )
    else:
        blockers.append(f"Unsupported training task: {task}")

    return TaskDatasetPreflight(
        task=task,
        blockers=blockers,
        warnings=warnings,
        box_count=box_count,
        polygon_count=polygon_count,
        raster_mask_count=raster_mask_count,
        polygon_counts_by_split=polygon_counts_by_split,
        raster_counts_by_split=raster_counts_by_split,
    )
