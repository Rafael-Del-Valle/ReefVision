"""Fail-closed integrity check for an existing saved QC workflow queue.

The queue's original scope checksum excludes mutable reviewer decisions. This
validator deliberately leaves review states, comments and assignments alone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from math import isfinite
from statistics import mean
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256


def validate_saved_queue_snapshot(queue: Any, items: Sequence[Any]) -> None:
    """Reject modified snapshot scope/count/order before a workflow retry.

    Validate persisted records only; never recalculate from live annotations.
    """
    invalid = ValidationError("Saved QC review queue snapshot failed integrity validation")
    # The generator stores the resolved QC source in both locations. A
    # workflow without an explicit source may select the latest historical
    # run, so compare persisted records rather than current QC state.
    configuration = queue.configuration_json
    if (
        not isinstance(configuration, dict)
        or "source_quality_control_run_id" not in configuration
        or configuration["source_quality_control_run_id"] != queue.source_quality_control_run_id
    ):
        raise invalid

    checksums = queue.input_checksums_json
    if not isinstance(checksums, dict):
        raise invalid

    # Historical snapshots may predate the scoring digest; retain their
    # compatibility while requiring internally consistent scoring metadata.
    # Newly generated queues include a digest so edits to the formula,
    # ruleset, thresholds or weights cannot silently change retry provenance.
    weights = configuration.get("weights")
    if (
        not isinstance(queue.formula_id, str)
        or not queue.formula_id.strip()
        or not isinstance(queue.formula_version, str)
        or not queue.formula_version.strip()
        or not isinstance(weights, dict)
        or not weights
        or any(
            not isinstance(signal, str)
            or not signal
            or type(weight) not in (int, float)
            or not isfinite(weight)
            or weight < 0
            for signal, weight in weights.items()
        )
    ):
        raise invalid
    scoring_digest = checksums.get("scoring_provenance_sha256")
    if scoring_digest is not None and (
        not isinstance(scoring_digest, str)
        or len(scoring_digest) != 64
        or any(char not in "0123456789abcdef" for char in scoring_digest)
        or scoring_digest
        != canonical_json_sha256(
            {
                "formula_id": queue.formula_id,
                "formula_version": queue.formula_version,
                "configuration": configuration,
            }
        )
    ):
        raise invalid
    saved_count = checksums.get("item_count")
    digest = checksums.get("queue_scope_sha256")
    if (
        type(saved_count) is not int
        or saved_count < 0
        or type(queue.item_count) is not int
        or queue.item_count != saved_count
        or len(items) != saved_count
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or queue.scope_type != "project"
        or queue.dataset_version_id is not None
    ):
        raise invalid

    scores: dict[str, float] = {}
    ranks: set[int] = set()
    for item in items:
        if (
            not isinstance(item.image_id, str)
            or not item.image_id
            or item.image_id in scores
            or item.project_id != queue.project_id
            or item.review_queue_id != queue.id
            or item.dataset_version_id is not None
            or item.weights_json != weights
            or type(item.rank_position) is not int
            or item.rank_position in ranks
            or type(item.score) not in (int, float)
            or not isfinite(item.score)
            or not 0 <= item.score <= 100
        ):
            raise invalid
        scores[item.image_id] = item.score
        ranks.add(item.rank_position)
    if ranks != set(range(1, saved_count + 1)):
        raise invalid

    # The queue creator ranks by descending priority and then image ID for
    # deterministic ties. The original scope digest does not encode ranks,
    # so two otherwise unchanged items could silently exchange priorities.
    saved_order = [item.image_id for item in sorted(items, key=lambda item: item.rank_position)]
    expected_order = [
        item.image_id for item in sorted(items, key=lambda item: (-item.score, item.image_id))
    ]
    if saved_order != expected_order:
        raise invalid

    # Queue creation saves a scientific summary separately from the scope
    # checksum. Reconstruct it only from the persisted queue items, never
    # from current annotations or mutable reviewer decisions.
    summary = queue.summary_json
    if not isinstance(summary, dict):
        raise invalid
    expected_average = round(mean(scores.values()), 2) if scores else 0.0
    stored_average = summary.get("average_score")
    if (
        not isinstance(stored_average, (int, float))
        or isinstance(stored_average, bool)
        or not isfinite(stored_average)
        or stored_average != expected_average
    ):
        raise invalid

    def matches_counts(field: str, expected: Counter[str]) -> bool:
        saved = summary.get(field)
        return (
            isinstance(saved, dict)
            and all(
                isinstance(key, str) and type(count) is int and count >= 0
                for key, count in saved.items()
            )
            and saved == dict(expected)
        )

    if (
        not matches_counts(
            "counts_by_severity",
            Counter(item.highest_qc_severity for item in items if item.highest_qc_severity),
        )
        or not matches_counts(
            "counts_by_split", Counter(item.split or "unspecified" for item in items)
        )
        or summary.get("top_image_ids") != saved_order[:10]
    ):
        raise invalid

    actual = canonical_json_sha256(
        {
            "image_ids": sorted(scores),
            "scores": scores,
            "source_quality_control_run_id": queue.source_quality_control_run_id,
        }
    )
    if actual != digest:
        raise invalid
