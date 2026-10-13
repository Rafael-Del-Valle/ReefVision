"""Never evaluate a segmentation candidate against unverified/leaky masks."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from reefvision.domain.segmentation_holdout import validate_segmentation_holdout


@dataclass
class Item:
    image_id: str = "img-a"
    split: str = "test"
    group_key: str | None = "colony-a"
    width_px: int = 20
    height_px: int = 20
    image_sha256: str = "a" * 64
    image_annotation_status: str = "reviewed"
    mask_annotation_count: int = 1
    mask_annotation_snapshot_json: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "mask-a",
                "label_class_id": "class-a",
                "status": "verified",
                "source_type": "human",
                "geometry_kind": "polygon",
                "polygon_json": [[2, 2], [10, 2], [10, 10], [2, 10]],
            }
        ]
    )


def check(items: list[Item], *, verify_raster=None):
    return validate_segmentation_holdout(
        items,
        split="test",
        minimum_images=1,
        minimum_masks=1,
        known_class_ids={"class-a"},
        verify_raster=verify_raster,
    )


def test_verified_group_safe_polygon_holdout() -> None:
    result = check(
        [
            Item(),
            Item(
                image_id="train-a",
                split="train",
                group_key="colony-b",
                mask_annotation_count=0,
                mask_annotation_snapshot_json=[],
            ),
        ]
    )
    assert result.image_ids == ("img-a",)
    assert result.group_ids == ("colony-a",)
    assert result.masks[0].class_id == "class-a"


def test_closed_ring_polygon_is_allowed() -> None:
    item = Item()
    item.mask_annotation_snapshot_json[0]["polygon_json"].append([2, 2])
    assert check([item]).masks[0].geometry_kind == "polygon"


@pytest.mark.parametrize(
    "polygon",
    [
        [[2, 2], [14, 14], [2, 14], [14, 2]],
        [[2, 2], [10, 2], [12, 30]],
        [[2, 2], [4, 4], [6, 6]],
        [[2, 2], [8, 2], [8, 2], [2, 8]],
        [[2, float("nan")], [8, 2], [2, 8]],
    ],
)
def test_unusable_polygon_fails_closed(polygon: list[list[float]]) -> None:
    item = Item()
    item.mask_annotation_snapshot_json[0]["polygon_json"] = polygon
    with pytest.raises(ValueError):
        check([item])


def test_group_leakage_detected_even_when_train_item_is_not_holdout() -> None:
    with pytest.raises(ValueError, match="group leakage"):
        check(
            [
                Item(),
                Item(
                    image_id="train-b",
                    split="train",
                    mask_annotation_count=0,
                    mask_annotation_snapshot_json=[],
                ),
            ]
        )


@pytest.mark.parametrize(
    "edit",
    [
        {"status": "draft"},
        {"source_type": "evaluation_only"},
        {"label_class_id": "unknown"},
        {"provenance_json": {"evaluation_only": True}},
    ],
)
def test_unverified_or_unmapped_mask_rejected(edit: dict[str, Any]) -> None:
    item = Item()
    item.mask_annotation_snapshot_json[0].update(edit)
    with pytest.raises(ValueError):
        check([item])


def test_image_review_and_mask_counts_are_mandatory() -> None:
    with pytest.raises(ValueError, match="human-reviewed"):
        check([replace(Item(), image_annotation_status="in_progress")])
    with pytest.raises(ValueError, match="mask count"):
        check([replace(Item(), mask_annotation_count=2)])


def test_verifies_raster_checksum_using_required_content_resolver() -> None:
    item = Item()
    item.mask_annotation_snapshot_json[0].update(
        {
            "geometry_kind": "raster_mask",
            "mask_path": "project/masks/instance.png",
            "mask_content_sha256": "b" * 64,
        }
    )
    with pytest.raises(ValueError, match="immutable content"):
        check([item])
    checks: list[tuple[str, str]] = []
    result = check([item], verify_raster=lambda path, digest: checks.append((path, digest)))
    assert checks == [("project/masks/instance.png", "b" * 64)]
    assert result.masks[0].content_sha256 == "b" * 64


def test_raster_checksum_failure_propagates() -> None:
    item = Item()
    item.mask_annotation_snapshot_json[0].update(
        {
            "geometry_kind": "raster_mask",
            "mask_path": "project/masks/corrupt.png",
            "mask_content_sha256": "b" * 64,
        }
    )

    def corrupted(_path: str, _digest: str) -> None:
        raise ValueError("Checksum mismatch")

    with pytest.raises(ValueError, match="Checksum mismatch"):
        check([item], verify_raster=corrupted)


def test_duplicate_image_and_mask_identifiers_rejected() -> None:
    with pytest.raises(ValueError, match="duplicated immutable snapshot image"):
        check([Item(), Item()])
    other = Item(image_id="img-b", group_key="colony-b")
    with pytest.raises(ValueError, match="duplicated verified mask"):
        check([Item(), other])


def test_insufficient_support_and_wrong_split_rejected() -> None:
    with pytest.raises(ValueError, match="insufficient verified support"):
        check([Item(split="train")])
    with pytest.raises(ValueError, match="Invalid segmentation holdout split"):
        validate_segmentation_holdout(
            [Item()],
            split="train",
            minimum_images=1,
            minimum_masks=1,
            known_class_ids=None,
            verify_raster=None,
        )
