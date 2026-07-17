from __future__ import annotations

from dataclasses import dataclass, field

from reefvision.services.training_tasks import (
    DETECTION_TASK,
    INSTANCE_SEGMENTATION_TASK,
    task_dataset_preflight,
)


@dataclass
class FakeDatasetItem:
    split: str
    annotation_count: int = 0
    mask_annotation_count: int = 0
    mask_annotation_snapshot_json: list[dict[str, object]] = field(default_factory=list)


def _mask(geometry_kind: str) -> dict[str, object]:
    return {"geometry_kind": geometry_kind}


def test_detection_preflight_requires_boxes() -> None:
    blocked = task_dataset_preflight(
        DETECTION_TASK,
        [FakeDatasetItem(split="train")],
    )
    assert blocked.ready is False
    assert blocked.blockers == [
        "Object-detection training requires at least one bounding box"
    ]

    ready = task_dataset_preflight(
        DETECTION_TASK,
        [FakeDatasetItem(split="train", annotation_count=2)],
    )
    assert ready.ready is True
    assert ready.box_count == 2


def test_instance_segmentation_preflight_counts_polygons_by_split() -> None:
    result = task_dataset_preflight(
        INSTANCE_SEGMENTATION_TASK,
        [
            FakeDatasetItem(
                split="train",
                mask_annotation_count=2,
                mask_annotation_snapshot_json=[_mask("polygon"), _mask("polygon")],
            ),
            FakeDatasetItem(
                split="validation",
                mask_annotation_count=1,
                mask_annotation_snapshot_json=[_mask("polygon")],
            ),
        ],
    )

    assert result.ready is True
    assert result.polygon_count == 3
    assert result.polygon_counts_by_split == {"train": 2, "validation": 1}
    assert result.raster_mask_count == 0
    assert result.warnings == []


def test_instance_segmentation_blocks_raster_only_dataset() -> None:
    result = task_dataset_preflight(
        INSTANCE_SEGMENTATION_TASK,
        [
            FakeDatasetItem(
                split="train",
                mask_annotation_count=1,
                mask_annotation_snapshot_json=[_mask("raster_mask")],
            )
        ],
    )

    assert result.ready is False
    assert result.polygon_count == 0
    assert result.raster_mask_count == 1
    assert result.blockers == [
        "Ultralytics instance-segmentation training requires at least one polygon mask",
        "The training split must contain at least one polygon mask for instance segmentation",
    ]
    assert result.warnings == [
        "The validation split contains no polygon masks, so segmentation metrics may be unavailable",
        "1 raster mask(s) will be excluded from YOLO polygon-segmentation training; use semantic-mask "
        "training or convert them to polygons",
    ]


def test_instance_segmentation_warns_without_validation_polygons_and_for_rasters() -> None:
    result = task_dataset_preflight(
        INSTANCE_SEGMENTATION_TASK,
        [
            FakeDatasetItem(
                split="train",
                mask_annotation_count=2,
                mask_annotation_snapshot_json=[_mask("polygon"), _mask("raster_mask")],
            )
        ],
    )

    assert result.ready is True
    assert result.polygon_count == 1
    assert result.raster_mask_count == 1
    assert result.warnings == [
        "The validation split contains no polygon masks, so segmentation metrics may be unavailable",
        "1 raster mask(s) will be excluded from YOLO polygon-segmentation training; use semantic-mask "
        "training or convert them to polygons",
    ]
