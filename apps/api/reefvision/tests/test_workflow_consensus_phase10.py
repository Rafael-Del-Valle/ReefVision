from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_consensus import build_detection_consensus


def _source(source_id: str, detections: list[dict[str, object]]) -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_kind": "test_model",
        "detections": detections,
    }


def _detection(
    proposal_id: str,
    *,
    image_id: str = "image-1",
    label: str = "open",
    label_class_id: str = "class-open",
    confidence: float = 0.9,
    box: tuple[float, float, float, float] = (10.0, 10.0, 30.0, 30.0),
) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "image_id": image_id,
        "label_class_id": label_class_id,
        "predicted_label": label,
        "confidence": confidence,
        "box": {
            "x_min": box[0],
            "y_min": box[1],
            "x_max": box[2],
            "y_max": box[3],
        },
    }


def test_two_of_three_detection_consensus_accepts_agreement_and_keeps_outlier() -> None:
    result = build_detection_consensus(
        [
            _source("gpt", [_detection("gpt-1")]),
            _source("gemini", [_detection("gemini-1", box=(11.0, 10.0, 31.0, 30.0))]),
            _source("claude", [_detection("claude-1", box=(70.0, 70.0, 90.0, 90.0))]),
        ],
        required_votes=2,
        iou_threshold=0.5,
    )

    assert result["source_count"] == 3
    assert result["consensus_count"] == 1
    assert result["disagreement_count"] == 1
    accepted = result["consensus"][0]
    assert accepted["vote_count"] == 2
    assert accepted["source_ids"] == ["gemini", "gpt"]
    assert accepted["box"]["x_min"] == pytest.approx(10.5)
    assert result["disagreements"][0]["source_ids"] == ["claude"]
    assert result["disagreements"][0]["reason"] == "insufficient_votes"


def test_three_of_three_requires_all_sources_to_agree() -> None:
    result = build_detection_consensus(
        [
            _source("gpt", [_detection("gpt-1")]),
            _source("gemini", [_detection("gemini-1", box=(11.0, 10.0, 31.0, 30.0))]),
            _source("claude", [_detection("claude-1", box=(70.0, 70.0, 90.0, 90.0))]),
        ],
        required_votes=3,
        iou_threshold=0.5,
    )

    assert result["consensus_count"] == 0
    assert result["disagreement_count"] == 2
    assert sorted(item["vote_count"] for item in result["disagreements"]) == [1, 2]


def test_duplicate_detections_from_one_source_never_create_extra_votes() -> None:
    result = build_detection_consensus(
        [
            _source(
                "gpt",
                [
                    _detection("gpt-1", confidence=0.95),
                    _detection("gpt-duplicate", confidence=0.80, box=(10.5, 10.0, 30.5, 30.0)),
                ],
            ),
            _source("gemini", []),
            _source("claude", []),
        ],
        required_votes=2,
        iou_threshold=0.5,
    )

    assert result["consensus_count"] == 0
    assert all(item["vote_count"] == 1 for item in result["disagreements"])


def test_class_aware_consensus_does_not_merge_different_classes() -> None:
    sources = [
        _source("gpt", [_detection("gpt-1")]),
        _source(
            "gemini",
            [
                _detection(
                    "gemini-closed",
                    label="closed",
                    label_class_id="class-closed",
                    box=(10.5, 10.0, 30.5, 30.0),
                )
            ],
        ),
    ]

    aware = build_detection_consensus(sources, required_votes=2, class_aware=True)
    assert aware["consensus_count"] == 0

    unaware = build_detection_consensus(sources, required_votes=2, class_aware=False)
    assert unaware["consensus_count"] == 1
    assert unaware["consensus"][0]["vote_count"] == 2


def test_consensus_rejects_impossible_vote_requirement() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        build_detection_consensus([_source("only", [])], required_votes=2)
