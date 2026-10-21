"""Regression coverage for saved QC queue retry integrity (no live rescoring)."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_review_queue_integrity import (
    validate_saved_queue_snapshot,
)
from reefvision.storage.datasets import canonical_json_sha256


def snapshot():
    items = [
        SimpleNamespace(
            image_id="img-a",
            project_id="p",
            review_queue_id="q",
            dataset_version_id=None,
            rank_position=1,
            score=80.0,
            review_state="pending",
        ),
        SimpleNamespace(
            image_id="img-b",
            project_id="p",
            review_queue_id="q",
            dataset_version_id=None,
            rank_position=2,
            score=20.0,
            review_state="pending",
        ),
    ]
    digest = canonical_json_sha256(
        {
            "image_ids": ["img-a", "img-b"],
            "scores": {"img-a": 80.0, "img-b": 20.0},
            "source_quality_control_run_id": None,
        }
    )
    queue = SimpleNamespace(
        id="q",
        project_id="p",
        scope_type="project",
        dataset_version_id=None,
        source_quality_control_run_id=None,
        item_count=2,
        input_checksums_json={"item_count": 2, "queue_scope_sha256": digest},
        configuration_json={"source_quality_control_run_id": None},
    )
    return queue, items


def test_valid_saved_snapshot_and_mutable_reviewer_state():
    queue, items = snapshot()
    validate_saved_queue_snapshot(queue, items)
    items[0].review_state = "completed"
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    "corruption",
    [
        "score",
        "duplicate_image",
        "rank",
        "swapped_ranks",
        "tie_order",
        "wrong_project",
        "wrong_queue",
        "count",
        "checksum",
        "missing_checksum",
        "source",
        "scope",
        "nan",
        "negative",
        "over_100",
        "boolean_count",
        "boolean_score",
        "missing_item",
    ],
)
def test_rejects_corrupted_saved_snapshot(corruption):
    queue, items = snapshot()
    queue, items = deepcopy((queue, items))
    if corruption == "score":
        items[0].score = 81.0
    elif corruption == "duplicate_image":
        items[1].image_id = "img-a"
    elif corruption == "rank":
        items[1].rank_position = 1
    elif corruption == "swapped_ranks":
        items[0].rank_position, items[1].rank_position = 2, 1
    elif corruption == "tie_order":
        # Even after a legitimate checksum update, tie ordering is defined
        # by image ID; a changed rank must not be silently accepted.
        items[1].score = 80.0
        items[0].rank_position, items[1].rank_position = 2, 1
        queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
            {
                "image_ids": ["img-a", "img-b"],
                "scores": {"img-a": 80.0, "img-b": 80.0},
                "source_quality_control_run_id": None,
            }
        )
    elif corruption == "wrong_project":
        items[0].project_id = "foreign"
    elif corruption == "wrong_queue":
        items[0].review_queue_id = "foreign"
    elif corruption == "count":
        queue.item_count = 3
    elif corruption == "checksum":
        queue.input_checksums_json["queue_scope_sha256"] = "a" * 64
    elif corruption == "missing_checksum":
        queue.input_checksums_json = {}
    elif corruption == "source":
        queue.source_quality_control_run_id = "foreign"
    elif corruption == "scope":
        queue.dataset_version_id = "dataset"
    elif corruption == "nan":
        items[0].score = float("nan")
    elif corruption == "negative":
        items[0].score = -1
    elif corruption == "over_100":
        items[0].score = 101
    elif corruption == "boolean_count":
        queue.input_checksums_json["item_count"] = True
    elif corruption == "boolean_score":
        items[0].score = True
    elif corruption == "missing_item":
        items.pop()
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)

@pytest.mark.parametrize("corruption", ["foreign", "missing", "not_mapping"])
def test_rejects_modified_saved_source_configuration(corruption):
    """A saved queue's resolved QC source must match its stored config."""
    queue, items = snapshot()
    if corruption == "foreign":
        queue.configuration_json["source_quality_control_run_id"] = "qc-run-other"
    elif corruption == "missing":
        queue.configuration_json.pop("source_quality_control_run_id")
    else:
        queue.configuration_json = None
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_automatic_source_run_id_is_not_required_to_be_none():
    """An omitted request source may resolve to a historical QC run."""
    queue, items = snapshot()
    queue.source_quality_control_run_id = "qc-run-auto"
    queue.configuration_json["source_quality_control_run_id"] = "qc-run-auto"
    queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
        {
            "image_ids": ["img-a", "img-b"],
            "scores": {"img-a": 80.0, "img-b": 20.0},
            "source_quality_control_run_id": "qc-run-auto",
        }
    )
    validate_saved_queue_snapshot(queue, items)
