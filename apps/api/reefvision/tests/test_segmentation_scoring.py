"""Regression tests for verified masks versus evaluation-only model output."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from reefvision.domain.segmentation_holdout import SegmentationHoldout, VerifiedMaskReference
from reefvision.services.segmentation_scoring import score_segmentation_holdout


@dataclass
class Item:
    image_id: str
    width_px: int
    height_px: int
    mask_annotation_snapshot_json: list[dict[str, Any]]


@dataclass
class Proposal:
    image_id: str = "image-1"
    model_id: str = "candidate-1"
    inference_job_id: str = "inference-1"
    model_checksum: str = "c" * 64
    label_class_id: str | None = "class-1"
    confidence: float = 0.92
    geometry_kind: str = "polygon_mask"
    polygon_json: list[list[float]] | None = None
    mask_path: str | None = None
    mask_content_sha256: str | None = None
    review_status: str = "evaluation_only"
    provenance_json: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.polygon_json is None:
            self.polygon_json = [[1, 1], [3, 1], [3, 3], [1, 3]]
        if self.provenance_json is None:
            self.provenance_json = {"evaluation_only": True, "model_task": "segment"}


def setup() -> tuple[SegmentationHoldout, list[Item], list[Proposal]]:
    truth_mask: dict[str, Any] = {
        "id": "mask-1",
        "status": "verified",
        "label_class_id": "class-1",
        "geometry_kind": "polygon",
        "polygon_json": [[1, 1], [3, 1], [3, 3], [1, 3]],
        "mask_path": None,
        "mask_content_sha256": None,
    }
    holdout = SegmentationHoldout(
        split="test",
        image_ids=("image-1",),
        group_ids=("colony-1",),
        masks=(VerifiedMaskReference("image-1", "mask-1", "class-1", "polygon", None, None),),
    )
    return holdout, [Item("image-1", 8, 8, [truth_mask])], [Proposal()]


def score(
    holdout: SegmentationHoldout,
    items: list[Item],
    proposals: list[Proposal],
    *,
    reader=None,
    **changes: Any,
):
    settings: dict[str, Any] = {
        "holdout": holdout,
        "snapshot_items": items,
        "proposals": proposals,
        "dataset_version_id": "version-1",
        "manifest_sha256": "a" * 64,
        "inference_job_id": "inference-1",
        "candidate_model_id": "candidate-1",
        "checkpoint_sha256": "c" * 64,
        "known_class_ids": {"class-1", "class-2"},
        "inference_succeeded": True,
        "read_managed_raster": reader or (lambda _path: b""),
    }
    settings.update(changes)
    return score_segmentation_holdout(**settings)


def test_identical_source_pixel_mask_scores_perfectly() -> None:
    holdout, items, proposals = setup()
    result = score(holdout, items, proposals)
    assert result.metrics.mask_map50 == 1
    assert result.metrics.mean_absolute_count_error == 0
    assert result.model_id == "candidate-1"


def test_empty_predictions_keep_heldout_count_error() -> None:
    holdout, items, _ = setup()
    result = score(holdout, items, [])
    assert result.metrics.mean_absolute_count_error == 1
    assert result.metrics.recall == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("review_status", "pending"),
        ("inference_job_id", "other-job"),
        ("model_id", "different-model"),
        ("model_checksum", "d" * 64),
        ("image_id", "outside-holdout"),
        ("label_class_id", "unknown"),
        ("geometry_kind", "bounding_box"),
        ("provenance_json", {"evaluation_only": False, "model_task": "segment"}),
        ("provenance_json", {"evaluation_only": True, "model_task": "detect"}),
    ],
)
def test_untrusted_or_unreviewed_predictions_rejected(field: str, value: Any) -> None:
    holdout, items, proposals = setup()
    setattr(proposals[0], field, value)
    with pytest.raises(ValueError):
        score(holdout, items, proposals)


def test_ground_truth_identity_mutation_rejected() -> None:
    holdout, items, proposals = setup()
    items[0].mask_annotation_snapshot_json[0]["label_class_id"] = "class-2"
    with pytest.raises(ValueError, match="differs from"):
        score(holdout, items, proposals)


def test_inference_not_succeeded_rejected() -> None:
    holdout, items, proposals = setup()
    with pytest.raises(ValueError, match="completed"):
        score(holdout, items, proposals, inference_succeeded=False)


def test_raster_bytes_checked_before_scoring_and_holes_preserved() -> None:
    holdout, items, proposals = setup()
    image = Image.new("L", (8, 8), 0)
    for pixel in [(1, 1), (3, 1), (1, 3), (3, 3)]:
        image.putpixel(pixel, 255)
    buf = BytesIO()
    image.save(buf, format="PNG")
    raw = buf.getvalue()
    checksum = sha256(raw).hexdigest()
    mask = items[0].mask_annotation_snapshot_json[0]
    mask.update(
        geometry_kind="raster_mask",
        polygon_json=None,
        mask_path="masks/a.png",
        mask_content_sha256=checksum,
    )
    holdout = SegmentationHoldout(
        "test",
        ("image-1",),
        ("colony-1",),
        (
            VerifiedMaskReference(
                "image-1", "mask-1", "class-1", "raster_mask", "masks/a.png", checksum
            ),
        ),
    )
    proposal = proposals[0]
    proposal.geometry_kind = "raster_mask"
    proposal.polygon_json = None
    proposal.mask_path = "masks/a.png"
    proposal.mask_content_sha256 = checksum
    result = score(holdout, items, proposals, reader=lambda path: raw)
    assert result.metrics.mask_map50 == 1
    with pytest.raises(ValueError, match="differs"):
        score(holdout, items, proposals, reader=lambda path: raw + b"changed")


def test_prediction_from_other_class_is_false_positive() -> None:
    holdout, items, proposals = setup()
    proposals[0].label_class_id = "class-2"
    result = score(holdout, items, proposals)
    assert result.metrics.mask_map50 == 0
    assert result.metrics.recall == 0
