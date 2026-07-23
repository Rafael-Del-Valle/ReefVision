from __future__ import annotations

import numpy as np
import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.mask_consensus import (
    IndependentMaskCandidate,
    build_mask_consensus,
)


def _mask(x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    result = np.zeros((20, 20), dtype=bool)
    result[y1:y2, x1:x2] = True
    return result


def _candidate(
    candidate_id: str,
    branch: str,
    mask: np.ndarray,
    confidence: float = 0.9,
    class_key: str = "coral",
) -> IndependentMaskCandidate:
    return IndependentMaskCandidate(
        candidate_id=candidate_id,
        branch_id=branch,
        image_id="image-1",
        class_key=class_key,
        confidence=confidence,
        mask=mask,
    )


def test_two_of_three_pixel_majority_keeps_pixels_supported_by_two_branches() -> None:
    sam3 = _mask(2, 2, 12, 12)
    gemini = _mask(4, 2, 14, 12)
    openai = _mask(4, 4, 12, 14)
    result = build_mask_consensus(
        [
            _candidate("sam3-a", "sam3", sam3),
            _candidate("gemini-a", "gemini_sam2", gemini),
            _candidate("openai-a", "openai_sam2", openai),
        ],
        required_votes=2,
        iou_threshold=0.3,
        aggregation="pixel_majority",
    )

    assert result.consensus_group_count == 1
    group = result.groups[0]
    expected = (sam3 & gemini) | (sam3 & openai) | (gemini & openai)
    assert np.array_equal(group.mask, expected)
    assert group.branch_ids == ("gemini_sam2", "openai_sam2", "sam3")
    assert set(group.candidate_ids) == {"sam3-a", "gemini-a", "openai-a"}


def test_intersection_is_more_conservative_than_majority() -> None:
    candidates = [
        _candidate("sam3-a", "sam3", _mask(2, 2, 12, 12)),
        _candidate("gemini-a", "gemini_sam2", _mask(4, 2, 14, 12)),
        _candidate("openai-a", "openai_sam2", _mask(4, 4, 12, 14)),
    ]
    intersection = build_mask_consensus(candidates, aggregation="intersection")
    majority = build_mask_consensus(candidates, aggregation="pixel_majority")

    assert int(intersection.groups[0].mask.sum()) < int(majority.groups[0].mask.sum())


def test_one_branch_cannot_cast_two_votes_for_one_instance() -> None:
    target = _mask(2, 2, 12, 12)
    result = build_mask_consensus(
        [
            _candidate("sam3-a", "sam3", target, 0.95),
            _candidate("sam3-duplicate", "sam3", _mask(3, 2, 13, 12), 0.80),
            _candidate("gemini-a", "gemini_sam2", _mask(2, 3, 12, 13), 0.90),
        ],
        required_votes=2,
        iou_threshold=0.3,
    )

    assert result.consensus_group_count == 1
    assert len(result.groups[0].branch_ids) == 2
    assert result.groups[0].branch_ids.count("sam3") == 1


def test_class_aware_matching_does_not_merge_different_classes() -> None:
    result = build_mask_consensus(
        [
            _candidate("sam3-a", "sam3", _mask(2, 2, 12, 12), class_key="coral"),
            _candidate(
                "gemini-a",
                "gemini_sam2",
                _mask(2, 2, 12, 12),
                class_key="sponge",
            ),
        ]
    )

    assert result.consensus_group_count == 0
    assert result.rejected_group_count == 2


def test_two_secondary_branches_can_reach_consensus_when_primary_misses() -> None:
    result = build_mask_consensus(
        [
            _candidate("gemini-a", "gemini_sam2", _mask(2, 2, 12, 12)),
            _candidate("openai-a", "openai_sam2", _mask(3, 2, 13, 12)),
        ],
        required_votes=2,
        iou_threshold=0.3,
    )

    assert result.consensus_group_count == 1
    assert result.groups[0].branch_ids == ("gemini_sam2", "openai_sam2")


def test_empty_intersection_is_rejected_with_warning() -> None:
    first = _mask(0, 0, 5, 5)
    second = _mask(4, 4, 9, 9)
    result = build_mask_consensus(
        [
            _candidate("a", "sam3", first),
            _candidate("b", "gemini_sam2", second),
        ],
        required_votes=2,
        iou_threshold=0.01,
        aggregation="intersection",
    )

    assert result.consensus_group_count == 1
    assert int(result.groups[0].mask.sum()) == 1


def test_rejects_shape_mismatch_and_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="share dimensions"):
        build_mask_consensus(
            [
                _candidate("a", "sam3", _mask(1, 1, 4, 4)),
                IndependentMaskCandidate(
                    candidate_id="b",
                    branch_id="gemini_sam2",
                    image_id="image-1",
                    class_key="coral",
                    confidence=0.9,
                    mask=np.ones((10, 10), dtype=bool),
                ),
            ]
        )

    with pytest.raises(ValidationError, match="IDs must be unique"):
        build_mask_consensus(
            [
                _candidate("a", "sam3", _mask(1, 1, 4, 4)),
                _candidate("a", "gemini_sam2", _mask(1, 1, 4, 4)),
            ]
        )
