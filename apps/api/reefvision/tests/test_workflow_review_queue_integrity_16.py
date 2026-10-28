"""Regression coverage for saved QC queue retry integrity (no live rescoring)."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.schemas.review_queues import ReviewScoreWeights
from reefvision.services.workflow_review_queue_integrity import (
    V3_SUPPORTED_SIGNALS,
    queue_item_evidence_sha256,
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
            weights_json={"signal": 1.0},
            input_checksum="a" * 64,
            label_class_ids_json=["class-a"],
            model_ids_json=["model-a"],
            related_issue_ids_json=["qc-issue-a"],
            signal_values_json={"signal": 0.8},
            normalized_signals_json={"signal": 0.8},
            score_breakdown_json=[
                {
                    "signal_id": "signal",
                    "label": "Signal",
                    "raw_value": 0.8,
                    "normalized_value": 0.8,
                    "weight": 1.0,
                    "contribution": 80.0,
                    "description": "Deterministic priority contribution",
                }
            ],
            reason_summary="Requires manual review",
            highest_qc_severity="warning",
            split="train",
            review_state="pending",
        ),
        SimpleNamespace(
            image_id="img-b",
            project_id="p",
            review_queue_id="q",
            dataset_version_id=None,
            rank_position=2,
            score=20.0,
            weights_json={"signal": 1.0},
            input_checksum="b" * 64,
            label_class_ids_json=["class-a"],
            model_ids_json=["model-a"],
            related_issue_ids_json=["qc-issue-a"],
            signal_values_json={"signal": 0.2},
            normalized_signals_json={"signal": 0.2},
            score_breakdown_json=[
                {
                    "signal_id": "signal",
                    "label": "Signal",
                    "raw_value": 0.2,
                    "normalized_value": 0.2,
                    "weight": 1.0,
                    "contribution": 20.0,
                    "description": "Deterministic priority contribution",
                }
            ],
            reason_summary="Requires manual review",
            highest_qc_severity=None,
            split=None,
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
        configuration_json={
            "source_quality_control_run_id": None,
            "weights": {"signal": 1.0},
            "ruleset_version": "qc-v1",
            "review_below_confidence": None,
        },
        formula_id="review_priority_v1",
        formula_version="1.0.0",
        summary_json={
            "average_score": 50.0,
            "counts_by_severity": {"warning": 1},
            "counts_by_split": {"train": 1, "unspecified": 1},
            "top_image_ids": ["img-a", "img-b"],
        },
    )
    queue.input_checksums_json["integrity_schema_version"] = "qc-review-queue-v2"
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    return queue, items


def test_valid_saved_snapshot_and_mutable_reviewer_state():
    queue, items = snapshot()
    validate_saved_queue_snapshot(queue, items)
    items[0].review_state = "completed"
    items[0].skip_reason = "Researcher requested a second look"
    validate_saved_queue_snapshot(queue, items)


def test_saved_evidence_digest_is_independent_of_database_row_order():
    """A saved workflow retry must not depend on ORM relationship load order."""
    queue, items = snapshot()
    original_digest = queue.input_checksums_json["item_evidence_sha256"]
    assert queue_item_evidence_sha256(list(reversed(items))) == original_digest
    validate_saved_queue_snapshot(queue, list(reversed(items)))


def test_reviewer_coordination_does_not_invalidate_scientific_snapshot():
    """Review coordination stays mutable without changing scientific provenance."""
    queue, items = snapshot()
    original_digest = queue.input_checksums_json["item_evidence_sha256"]
    items[0].review_state = "in_progress"
    items[0].assigned_to = "reviewer-2"
    items[0].skip_reason = "Needs specialist verification"
    items[0].review_comment = "Check colony identity"
    assert queue_item_evidence_sha256(items) == original_digest
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
        "formula_id",
        "formula_version",
        "configuration_weights",
        "item_weights",
        "missing_formula",
        "nonfinite_weight",
        "boolean_weight",
        "scoring_digest",
        "item_evidence_digest",
        "input_checksum",
        "score_breakdown",
        "normalized_signal",
        "class_reference",
        "reason_summary",
        "raw_signal_nan",
        "normalized_signal_infinity",
        "normalized_signal_negative",
        "normalized_signal_above_one",
        "breakdown_contribution_nan",
        "breakdown_weight_boolean",
        "missing_normalized_signal",
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
    elif corruption == "formula_id":
        queue.formula_id = "unreviewed_formula"
    elif corruption == "formula_version":
        queue.formula_version = "99.0.0"
    elif corruption == "configuration_weights":
        queue.configuration_json["weights"]["signal"] = 2.0
    elif corruption == "item_weights":
        items[0].weights_json["signal"] = 2.0
    elif corruption == "missing_formula":
        queue.formula_version = ""
    elif corruption == "nonfinite_weight":
        queue.configuration_json["weights"]["signal"] = float("nan")
    elif corruption == "boolean_weight":
        queue.configuration_json["weights"]["signal"] = True
    elif corruption == "scoring_digest":
        queue.input_checksums_json["scoring_provenance_sha256"] = "0" * 64
    elif corruption == "item_evidence_digest":
        queue.input_checksums_json["item_evidence_sha256"] = "0" * 64
    elif corruption == "input_checksum":
        items[0].input_checksum = "f" * 64
    elif corruption == "score_breakdown":
        items[0].score_breakdown_json[0]["contribution"] = 10.0
    elif corruption == "normalized_signal":
        items[0].normalized_signals_json["signal"] = 0.1
    elif corruption == "class_reference":
        items[0].label_class_ids_json.append("other-class")
    elif corruption == "reason_summary":
        items[0].reason_summary = "Altered scientific explanation"
    elif corruption == "raw_signal_nan":
        items[0].signal_values_json["signal"] = float("nan")
    elif corruption == "normalized_signal_infinity":
        items[0].normalized_signals_json["signal"] = float("inf")
    elif corruption == "normalized_signal_negative":
        items[0].normalized_signals_json["signal"] = -0.1
    elif corruption == "normalized_signal_above_one":
        items[0].normalized_signals_json["signal"] = 1.1
    elif corruption == "breakdown_contribution_nan":
        items[0].score_breakdown_json[0]["contribution"] = float("nan")
    elif corruption == "breakdown_weight_boolean":
        items[0].score_breakdown_json[0]["weight"] = True
    elif corruption == "missing_normalized_signal":
        items[0].normalized_signals_json.clear()
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


def test_historical_snapshot_without_item_evidence_digest_remains_readable():
    """Old queues retain their prior integrity checks without forced migration."""
    queue, items = snapshot()
    queue.input_checksums_json.pop("integrity_schema_version")
    queue.input_checksums_json.pop("item_evidence_sha256")
    validate_saved_queue_snapshot(queue, items)


def test_historical_snapshot_without_scoring_digest_remains_readable():
    """Older persisted workflow queues must remain retryable without rescoring."""
    queue, items = snapshot()
    queue.input_checksums_json.pop("integrity_schema_version")
    queue.input_checksums_json.pop("scoring_provenance_sha256")
    validate_saved_queue_snapshot(queue, items)
    items[0].weights_json["signal"] = 2.0
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize("missing_digest", ["scoring_provenance_sha256", "item_evidence_sha256"])
def test_versioned_queue_fails_closed_when_provenance_digest_is_missing(missing_digest):
    queue, items = snapshot()
    queue.input_checksums_json.pop(missing_digest)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    ("formula_id", "formula_version"),
    [
        ("unreviewed_scoring_formula", "1.0.0"),
        ("review_priority_v1", "99.0.0"),
    ],
)
def test_versioned_queue_rejects_resigned_unknown_scoring_formula(
    formula_id: str, formula_version: str
) -> None:
    """A re-signed digest cannot authorize an unknown biological QC formula."""
    queue, items = snapshot()
    original_digest = queue.input_checksums_json["scoring_provenance_sha256"]
    queue.formula_id = formula_id
    queue.formula_version = formula_version
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
        }
    )
    assert queue.input_checksums_json["scoring_provenance_sha256"] != original_digest
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("review_below_confidence", -0.01),
        ("review_below_confidence", 1.01),
        ("review_below_confidence", True),
        ("review_below_confidence", "0.5"),
        ("ruleset_version", ""),
        ("ruleset_version", None),
        ("ruleset_version", False),
    ],
)
def test_v2_rejects_resigned_invalid_qc_selection_provenance(
    field: str, invalid_value: object
) -> None:
    """A matching digest cannot legitimize invalid QC selection metadata."""
    queue, items = snapshot()
    queue.configuration_json[field] = invalid_value
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
        }
    )
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_unversioned_legacy_formula_remains_readable_with_matching_digest() -> None:
    """Do not retroactively reject historical unversioned research queues."""
    queue, items = snapshot()
    queue.input_checksums_json.pop("integrity_schema_version")
    queue.formula_version = "0.9.0"
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
        }
    )
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    "integrity_version",
    ["unknown-version", {"version": "v3"}, ["v3"], True],
)
def test_rejects_unknown_saved_queue_integrity_version(integrity_version):
    queue, items = snapshot()
    queue.input_checksums_json["integrity_schema_version"] = integrity_version
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_unversioned_legacy_queue_without_both_digests_remains_readable():
    queue, items = snapshot()
    queue.input_checksums_json.pop("integrity_schema_version")
    queue.input_checksums_json.pop("scoring_provenance_sha256")
    queue.input_checksums_json.pop("item_evidence_sha256")
    validate_saved_queue_snapshot(queue, items)


def test_automatic_source_run_id_is_not_required_to_be_none():
    """An omitted request source may resolve to a historical QC run."""
    queue, items = snapshot()
    queue.source_quality_control_run_id = "qc-run-auto"
    queue.configuration_json["source_quality_control_run_id"] = "qc-run-auto"
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
        }
    )
    queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
        {
            "image_ids": ["img-a", "img-b"],
            "scores": {"img-a": 80.0, "img-b": 20.0},
            "source_quality_control_run_id": "qc-run-auto",
        }
    )
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "average",
        "nonfinite_average",
        "boolean_average",
        "severity",
        "split",
        "top_image_ids",
        "negative_count",
        "boolean_count",
    ],
)
def test_rejects_corrupted_saved_scientific_summary(corruption):
    queue, items = snapshot()
    if corruption == "missing":
        queue.summary_json = None
    elif corruption == "average":
        queue.summary_json["average_score"] = 51.0
    elif corruption == "nonfinite_average":
        queue.summary_json["average_score"] = float("nan")
    elif corruption == "boolean_average":
        queue.summary_json["average_score"] = True
    elif corruption == "severity":
        queue.summary_json["counts_by_severity"] = {"error": 1}
    elif corruption == "split":
        queue.summary_json["counts_by_split"] = {"train": 2}
    elif corruption == "top_image_ids":
        queue.summary_json["top_image_ids"] = ["img-b", "img-a"]
    elif corruption == "negative_count":
        queue.summary_json["counts_by_severity"] = {"warning": -1}
    elif corruption == "boolean_count":
        queue.summary_json["counts_by_severity"] = {"warning": True}
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_empty_saved_queue_summary_is_valid():
    queue, _items = snapshot()
    queue.item_count = 0
    queue.input_checksums_json = {
        "item_count": 0,
        "queue_scope_sha256": canonical_json_sha256(
            {
                "image_ids": [],
                "scores": {},
                "source_quality_control_run_id": None,
            }
        ),
    }
    queue.summary_json = {
        "average_score": 0.0,
        "counts_by_severity": {},
        "counts_by_split": {},
        "top_image_ids": [],
    }
    validate_saved_queue_snapshot(queue, [])


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong_raw_value",
        "wrong_normalized_value",
        "wrong_weight",
        "wrong_contribution",
        "missing_component",
        "duplicate_component",
        "unknown_signal",
        "raw_signal_disagreement",
        "normalized_signal_disagreement",
        "unregistered_signal",
    ],
)
def test_v2_rejects_resigned_inconsistent_scientific_explanation(corruption):
    """A valid digest cannot excuse an internally false saved score explanation."""
    queue, items = snapshot()
    part = items[0].score_breakdown_json[0]
    if corruption == "wrong_raw_value":
        part["raw_value"] = 0.1
    elif corruption == "wrong_normalized_value":
        part["normalized_value"] = 0.1
    elif corruption == "wrong_weight":
        part["weight"] = 2.0
    elif corruption == "wrong_contribution":
        part["contribution"] = 70.0
    elif corruption == "missing_component":
        items[0].score_breakdown_json.clear()
    elif corruption == "duplicate_component":
        items[0].score_breakdown_json.append(dict(part))
    elif corruption == "unknown_signal":
        part["signal_id"] = "unknown"
    elif corruption == "raw_signal_disagreement":
        items[0].signal_values_json["signal"] = 0.5
    elif corruption == "normalized_signal_disagreement":
        items[0].normalized_signals_json["signal"] = 0.7
    elif corruption == "unregistered_signal":
        items[0].signal_values_json["unknown"] = 0.5
        items[0].normalized_signals_json["unknown"] = 0.5
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_v2_rejects_resigned_omission_of_configured_scoring_signal():
    """A re-signed snapshot cannot silently omit a configured QC signal."""
    queue, items = snapshot()
    for item in items:
        item.signal_values_json = {}
        item.normalized_signals_json = {}
        item.score_breakdown_json = []
        item.score = 0.0
    queue.summary_json["average_score"] = 0.0
    queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
        {
            "image_ids": ["img-a", "img-b"],
            "scores": {"img-a": 0.0, "img-b": 0.0},
            "source_quality_control_run_id": None,
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_v2_rejects_resigned_score_with_updated_scope_and_summary():
    """All recorded digests and summary may agree while the score formula does not."""
    queue, items = snapshot()
    items[0].score = 79.0
    queue.summary_json["average_score"] = 49.5
    queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
        {
            "image_ids": ["img-a", "img-b"],
            "scores": {"img-a": 79.0, "img-b": 20.0},
            "source_quality_control_run_id": None,
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_v2_rejects_resigned_zero_total_weight_even_when_scores_agree():
    """A checksum-consistent all-zero vector must not define a v2 priority score."""
    queue, items = snapshot()
    queue.configuration_json["weights"] = {"signal": 0.0}
    for item in items:
        item.weights_json = {"signal": 0.0}
        item.score = 0.0
        item.score_breakdown_json[0]["weight"] = 0.0
        item.score_breakdown_json[0]["contribution"] = 0.0
    queue.summary_json["average_score"] = 0.0
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
        }
    )
    queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
        {
            "image_ids": ["img-a", "img-b"],
            "scores": {"img-a": 0.0, "img-b": 0.0},
            "source_quality_control_run_id": None,
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)

    # Historical unversioned queues remain readable without rewriting data.
    queue.input_checksums_json.pop("integrity_schema_version")
    validate_saved_queue_snapshot(queue, items)


def _v3_snapshot():
    """Create a coherent synthetic v3 snapshot with all 13 frozen QC inputs."""
    queue, items = snapshot()
    weights = {signal: 0.0 for signal in V3_SUPPORTED_SIGNALS}
    weights["low_mean_confidence"] = 1.0
    queue.configuration_json["weights"] = weights
    for item in items:
        original = item.normalized_signals_json["signal"]
        raw = {signal: 0.0 for signal in V3_SUPPORTED_SIGNALS}
        raw["low_mean_confidence"] = original
        item.weights_json = dict(weights)
        item.signal_values_json = raw
        item.normalized_signals_json = dict(raw)
        item.score_breakdown_json = sorted(
            [
                {
                    "signal_id": signal,
                    "label": signal,
                    "raw_value": value,
                    "normalized_value": round(value, 6),
                    "weight": weights[signal],
                    "contribution": round(value * weights[signal] * 100, 2),
                    "description": "Synthetic QC priority contribution",
                }
                for signal, value in raw.items()
            ],
            key=lambda part: (-part["contribution"], part["signal_id"]),
        )
    queue.input_checksums_json["integrity_schema_version"] = "qc-review-queue-v3"
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
            "integrity_schema_version": "qc-review-queue-v3",
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    return queue, items


def test_v3_scientific_signal_contract_matches_queue_generator_schema():
    """The frozen v3 formula must enumerate every generated scoring input."""
    assert set(ReviewScoreWeights.model_fields) == V3_SUPPORTED_SIGNALS
    queue, items = _v3_snapshot()
    validate_saved_queue_snapshot(queue, items)
    items[0].review_state = "completed"
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize("corruption", ["invented_signal", "omitted_signal"])
def test_v3_rejects_resigned_coherent_signal_set_changes(corruption):
    """A complete re-sign of plausible scores cannot redefine the formula."""
    queue, items = _v3_snapshot()
    if corruption == "invented_signal":
        queue.configuration_json["weights"]["invented_biological_signal"] = 0.0
        for item in items:
            item.weights_json["invented_biological_signal"] = 0.0
            item.signal_values_json["invented_biological_signal"] = 0.0
            item.normalized_signals_json["invented_biological_signal"] = 0.0
            item.score_breakdown_json.append(
                {
                    "signal_id": "invented_biological_signal",
                    "label": "Unapproved biological signal",
                    "raw_value": 0.0,
                    "normalized_value": 0.0,
                    "weight": 0.0,
                    "contribution": 0.0,
                    "description": "Unreviewed scoring component",
                }
            )
            item.score_breakdown_json.sort(
                key=lambda part: (-part["contribution"], part["signal_id"])
            )
    else:
        queue.configuration_json["weights"].pop("stale_review_state")
        for item in items:
            item.weights_json.pop("stale_review_state")
            item.signal_values_json.pop("stale_review_state")
            item.normalized_signals_json.pop("stale_review_state")
            item.score_breakdown_json = [
                part
                for part in item.score_breakdown_json
                if part["signal_id"] != "stale_review_state"
            ]
    # Both digests are recomputed. All remaining numeric scores, ranks,
    # review states and the scientific summary are internally consistent.
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
            "integrity_schema_version": "qc-review-queue-v3",
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_v3_integrity_marker_cannot_be_accidentally_downgraded():
    """Changing the schema marker alone must invalidate its versioned digest."""
    queue, items = _v3_snapshot()
    queue.input_checksums_json["integrity_schema_version"] = "qc-review-queue-v2"
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    ("signal_id", "altered_raw"),
    [
        ("low_mean_confidence", 0.1),
        ("pending_proposals", 5.0),
        ("pending_proposals", -1.0),
        ("pending_proposals", 1.5),
        ("rejection_rate", 1.2),
    ],
)
def test_v3_rejects_resigned_false_raw_normalization(signal_id: str, altered_raw: float) -> None:
    """A re-signed, score-consistent snapshot cannot invent raw QC evidence."""
    queue, items = _v3_snapshot()
    item = items[0]
    item.signal_values_json[signal_id] = altered_raw
    part = next(part for part in item.score_breakdown_json if part["signal_id"] == signal_id)
    part["raw_value"] = altered_raw
    # The old v2 check sees internally consistent breakdown, score and
    # checksum; only v3's scientific normalization rule detects this edit.
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize("pending_count", [0, 5, 10, 15, 0.0, 5.0, 10.0, 15.0])
def test_v3_accepts_real_pending_count_normalization(pending_count: int | float) -> None:
    """Valid raw counts saturate at ten without rewriting reviewer history."""
    queue, items = _v3_snapshot()
    normalized = min(pending_count / 10.0, 1.0)
    for item in items:
        item.signal_values_json["pending_proposals"] = pending_count
        item.normalized_signals_json["pending_proposals"] = normalized
        part = next(
            part for part in item.score_breakdown_json if part["signal_id"] == "pending_proposals"
        )
        part["raw_value"] = pending_count
        part["normalized_value"] = normalized
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    ("signal_id", "false_flag"),
    [
        ("unreviewed_state", 0.5),
        ("unreviewed_state", 0.25),
        ("missing_group_metadata", 0.5),
        ("missing_group_metadata", 0.75),
    ],
)
def test_v3_rejects_resigned_fractional_binary_qc_flags(
    signal_id: str, false_flag: float
) -> None:
    """A matching checksum and score cannot turn a yes/no observation into a fraction."""
    queue, items = _v3_snapshot()
    item = items[0]
    item.signal_values_json[signal_id] = false_flag
    item.normalized_signals_json[signal_id] = false_flag
    part = next(part for part in item.score_breakdown_json if part["signal_id"] == signal_id)
    part["raw_value"] = false_flag
    part["normalized_value"] = false_flag
    # The signal has zero weight in this fixture. Its score, summary, rank,
    # and other evidence remain consistent after the digest is recomputed.
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize("signal_id", ["unreviewed_state", "missing_group_metadata"])
@pytest.mark.parametrize("flag", [0, 1, 0.0, 1.0])
def test_v3_accepts_genuine_binary_qc_flags(signal_id: str, flag: int | float) -> None:
    """Both possible flag states remain valid, including legacy integer JSON values."""
    queue, items = _v3_snapshot()
    for item in items:
        item.signal_values_json[signal_id] = flag
        item.normalized_signals_json[signal_id] = flag
        part = next(part for part in item.score_breakdown_json if part["signal_id"] == signal_id)
        part["raw_value"] = flag
        part["normalized_value"] = flag
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    "field",
    [
        "scoring_weight",
        "confidence_threshold",
        "priority_score",
        "raw_signal",
        "normalized_signal",
        "breakdown_value",
        "summary_average",
    ],
)
def test_saved_qc_snapshot_rejects_oversized_json_integer_without_overflow(
    field: str,
) -> None:
    """A corrupted persisted JSON integer must fail closed, never raise OverflowError."""
    queue, items = snapshot()
    huge = 10**400  # Valid Python/JSON integer, but math.isfinite cannot convert it.
    if field == "scoring_weight":
        queue.configuration_json["weights"]["signal"] = huge
    elif field == "confidence_threshold":
        queue.configuration_json["review_below_confidence"] = huge
    elif field == "priority_score":
        items[0].score = huge
    elif field == "raw_signal":
        items[0].signal_values_json["signal"] = huge
    elif field == "normalized_signal":
        items[0].normalized_signals_json["signal"] = huge
    elif field == "breakdown_value":
        items[0].score_breakdown_json[0]["raw_value"] = huge
    else:
        queue.summary_json["average_score"] = huge
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_v3_saved_pending_count_rejects_oversized_integer_without_overflow() -> None:
    """The frozen v3 count normalization also rejects unrepresentable JSON numbers."""
    queue, items = _v3_snapshot()
    items[0].signal_values_json["pending_proposals"] = 10**400
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)
