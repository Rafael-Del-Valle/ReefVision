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

# V2 scientific explanations implement exactly this deterministic scoring
# contract. A future scoring algorithm must receive a new integrity version,
# not merely a newly computed checksum on an old saved workflow.
V2_SUPPORTED_FORMULA = ("review_priority_v1", "1.0.0")
SUPPORTED_INTEGRITY_VERSIONS = ("qc-review-queue-v2", "qc-review-queue-v3")
# Frozen scientific inputs for v3. A future scoring formula must introduce a
# new version rather than silently adding or dropping biological/QC signals.
# Human-readable explanations are scientific evidence too: a re-signed v3
# snapshot must not call an unverified QC signal a verified biological result.
# Keep these labels shared with the queue generator to prevent drift.
V3_SIGNAL_LABELS = {
    "low_mean_confidence": "Low mean prediction confidence",
    "low_min_confidence": "Low minimum prediction confidence",
    "pending_proposals": "Many pending proposals",
    "rejection_rate": "High proposal rejection rate",
    "count_disagreement": "Model-versus-human count gap",
    "unresolved_qc_severity": "Unresolved QC severity",
    "rare_class_presence": "Rare-class presence",
    "edited_acceptance_rate": "Edited acceptance rate",
    "unreviewed_state": "Image not marked reviewed",
    "missing_group_metadata": "Missing group metadata",
    "incomplete_provenance": "Incomplete provenance",
    "recent_import": "Recently imported image",
    "stale_review_state": "Stale review state",
}
V3_SUPPORTED_SIGNALS = frozenset(V3_SIGNAL_LABELS)


def _finite_scientific_number(value: Any) -> bool:
    """Reject booleans, NaN and infinity in saved numeric QC evidence."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        # Python cannot convert arbitrarily large JSON integers to a float.
        # Treat malformed saved evidence as invalid, not an uncaught 500.
        return False


def _valid_v2_score_explanation(item: Any, weights: dict[str, float]) -> bool:
    """Cross-check saved component explanations against the deterministic formula.

    A checksum alone cannot establish that a re-signed saved explanation is
    scientifically self-consistent. Compare against persisted signals only:
    never rescore live annotations or change mutable reviewer decisions.
    """
    raw = item.signal_values_json
    normalized = item.normalized_signals_json
    breakdown = item.score_breakdown_json
    if (
        not isinstance(raw, dict)
        or not isinstance(normalized, dict)
        or not isinstance(breakdown, list)
        or raw.keys() != normalized.keys()
        or len(breakdown) != len(raw)
        or raw.keys() != weights.keys()
        or any(not _finite_scientific_number(value) for value in raw.values())
        or any(
            not _finite_scientific_number(value) or not 0 <= value <= 1
            for value in normalized.values()
        )
    ):
        return False

    # New versioned snapshots must not reinterpret an all-zero scoring vector
    # as a meaningful priority formula. Legacy unversioned queues retain their
    # existing compatibility path without invoking this validator.
    # Sum as floats: each valid JSON integer is representable, but their
    # integer total might overflow during a later float conversion.
    total_weight = sum(float(weight) for weight in weights.values())
    if not isfinite(total_weight) or total_weight <= 0:
        return False

    seen: set[str] = set()
    for part in breakdown:
        if not isinstance(part, dict):
            return False
        signal_id = part.get("signal_id")
        if (
            not isinstance(signal_id, str)
            or signal_id not in raw
            or signal_id in seen
            or any(
                not _finite_scientific_number(part.get(field))
                for field in ("raw_value", "normalized_value", "weight", "contribution")
            )
        ):
            return False
        seen.add(signal_id)
        expected_contribution = round(
            (normalized[signal_id] * weights[signal_id] / total_weight) * 100.0, 2
        )
        if (
            part["raw_value"] != float(raw[signal_id])
            or part["normalized_value"] != round(normalized[signal_id], 6)
            or part["weight"] != float(weights[signal_id])
            or part["contribution"] != expected_contribution
        ):
            return False

    expected_score = round(
        sum(normalized[signal] * weights[signal] / total_weight * 100.0 for signal in raw),
        2,
    )
    return (
        len(seen) == len(raw)
        and item.score == expected_score
        and breakdown
        == sorted(breakdown, key=lambda part: (-part["contribution"], part["signal_id"]))
    )


def _valid_v3_scientific_explanation(item: Any) -> bool:
    """Validate frozen human-readable QC explanations, not only numeric scores.

    Versioned queue labels and the short summary must never imply biological
    verification or a different signal after a persisted artifact is re-signed.
    This checks immutable evidence only, not editable reviewer comments.
    """
    breakdown = item.score_breakdown_json
    if not isinstance(breakdown, list):
        return False
    for part in breakdown:
        if not isinstance(part, dict):
            return False
        signal_id = part.get("signal_id")
        if not isinstance(signal_id, str) or signal_id not in V3_SIGNAL_LABELS:
            return False
        label = V3_SIGNAL_LABELS[signal_id]
        if (
            part.get("label") != label
            or part.get("description")
            != f"{label} contributes according to the configured deterministic weight."
        ):
            return False
    expected_summary = ", ".join(
        f"{part['label']}: +{part['contribution']:.2f}"
        for part in breakdown[:4]
        if part["contribution"] > 0
    )
    return item.reason_summary == (expected_summary or None)


def _valid_v3_signal_normalization(item: Any) -> bool:
    """Reproduce the frozen v3 normalization from persisted raw QC signals.

    A re-signed checksum and internally consistent score do not establish that
    the recorded normalized values were actually derived from raw evidence.
    Check only immutable saved values, never live annotations or review state.
    """
    raw = item.signal_values_json
    normalized = item.normalized_signals_json
    if not isinstance(raw, dict) or not isinstance(normalized, dict):
        return False
    for signal_id in V3_SUPPORTED_SIGNALS:
        value = raw.get(signal_id)
        # Narrow the persisted JSON value to a real numeric type for both
        # runtime validation and strict static typing. bool is an int subclass
        # but must never count as a biological observation.
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if not _finite_scientific_number(value):
            return False
        if signal_id == "pending_proposals":
            # The generator records a nonnegative integer count as a float,
            # saturating its priority signal at ten pending proposals.
            if value < 0 or value % 1 != 0:
                return False
            expected = min(value / 10.0, 1.0)
        elif signal_id in {"unreviewed_state", "missing_group_metadata"}:
            # These flags are emitted only as 0 or 1. A fractional flag
            # is not a valid observation even when its digest is re-signed.
            if value not in (0.0, 1.0):
                return False
            expected = value
        else:
            # Remaining v3 signals are bounded proportions, confidences
            # or normalized QC severity scores.
            if not 0 <= value <= 1:
                return False
            expected = value
        if normalized.get(signal_id) != expected:
            return False
    return True



def _valid_v3_scientific_references(item: Any) -> bool:
    """Reject re-signed, malformed QC source references without querying live data.

    The queue generator stores canonical, sorted unique ID lists and a
    lowercase SHA-256 input fingerprint. A digest alone does not prevent a
    corrupted saved workflow from inventing references to scientific evidence.
    This contract applies only to new v3 snapshots, not historical queues.
    """
    for field in ("label_class_ids_json", "model_ids_json", "related_issue_ids_json"):
        values = getattr(item, field, None)
        if (
            not isinstance(values, list)
            or any(type(value) is not str or not value or value != value.strip() for value in values)
            or values != sorted(set(values))
        ):
            return False
    checksum = getattr(item, "input_checksum", None)
    return (
        type(checksum) is str
        and len(checksum) == 64
        and all(char in "0123456789abcdef" for char in checksum)
        and item.highest_qc_severity in (None, "info", "warning", "error")
    )


def queue_item_evidence_sha256(items: Sequence[Any]) -> str:
    """Digest immutable scientific queue evidence, excluding mutable reviewer decisions.

    Sort by image identity, not query order, so database retrieval order cannot
    change a valid digest. A changed score, priority, signal explanation, input
    fingerprint, or biological/QC source reference invalidates saved replay.
    """
    return canonical_json_sha256(
        [
            {
                "image_id": item.image_id,
                "rank_position": item.rank_position,
                "score": item.score,
                "input_checksum": item.input_checksum,
                "split": item.split,
                "highest_qc_severity": item.highest_qc_severity,
                "label_class_ids": item.label_class_ids_json,
                "model_ids": item.model_ids_json,
                "related_issue_ids": item.related_issue_ids_json,
                "signal_values": item.signal_values_json,
                "normalized_signals": item.normalized_signals_json,
                "weights": item.weights_json,
                "score_breakdown": item.score_breakdown_json,
                "reason_summary": item.reason_summary,
            }
            for item in sorted(items, key=lambda row: row.image_id)
        ]
    )


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

    # Queues written with the v2 contract must retain both independent
    # digests. Older unversioned queues remain readable without a migration.
    integrity_version = checksums.get("integrity_schema_version")
    if integrity_version is not None and integrity_version not in SUPPORTED_INTEGRITY_VERSIONS:
        raise invalid
    if (
        integrity_version in SUPPORTED_INTEGRITY_VERSIONS
        and (queue.formula_id, queue.formula_version) != V2_SUPPORTED_FORMULA
    ):
        raise invalid
    if integrity_version in SUPPORTED_INTEGRITY_VERSIONS and (
        "scoring_provenance_sha256" not in checksums or "item_evidence_sha256" not in checksums
    ):
        raise invalid

    # Historical snapshots may predate the scoring digest; retain their
    # compatibility while requiring internally consistent scoring metadata.
    # Newly generated queues include a digest so edits to the formula,
    # ruleset, thresholds or weights cannot silently change retry provenance.
    # The v2 scoring contract also requires valid selection provenance.
    # Re-signing a digest must not authorize a nonphysical confidence gate
    # or an absent QC ruleset. Historical unversioned queues are untouched.
    if integrity_version in SUPPORTED_INTEGRITY_VERSIONS:
        threshold = configuration.get("review_below_confidence")
        ruleset = configuration.get("ruleset_version")
        if (
            type(ruleset) is not str
            or not ruleset.strip()
            or (
                threshold is not None
                and (not _finite_scientific_number(threshold) or not 0 <= threshold <= 1)
            )
        ):
            raise invalid
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
            or not _finite_scientific_number(weight)
            or weight < 0
            for signal, weight in weights.items()
        )
    ):
        raise invalid
    # v3 freezes the complete set of formula inputs. A re-signed checksum
    # must not permit adding an invented signal or omitting a known one.
    # Historical v2 queues retain their original compatibility contract.
    if integrity_version == "qc-review-queue-v3" and set(weights) != V3_SUPPORTED_SIGNALS:
        raise invalid
    scoring_digest = checksums.get("scoring_provenance_sha256")
    if scoring_digest is not None:
        scoring_payload: dict[str, Any] = {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": configuration,
        }
        if integrity_version == "qc-review-queue-v3":
            scoring_payload["integrity_schema_version"] = integrity_version
        expected_scoring_digest = canonical_json_sha256(scoring_payload)
        if (
            not isinstance(scoring_digest, str)
            or len(scoring_digest) != 64
            or any(char not in "0123456789abcdef" for char in scoring_digest)
            or scoring_digest != expected_scoring_digest
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
            or not _finite_scientific_number(item.score)
            or not 0 <= item.score <= 100
        ):
            raise invalid
        # Versioned snapshots must preserve both finite scientific evidence
        # and its deterministic per-signal/aggregate score explanation.
        if integrity_version in SUPPORTED_INTEGRITY_VERSIONS and not _valid_v2_score_explanation(
            item, weights
        ):
            raise invalid
        if integrity_version == "qc-review-queue-v3" and (
            not _valid_v3_signal_normalization(item)
            or not _valid_v3_scientific_explanation(item)
            or not _valid_v3_scientific_references(item)
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
    if not _finite_scientific_number(stored_average) or stored_average != expected_average:
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

    # Legacy queues lack this field. New queues protect their full immutable
    # scientific explanations as well as score/scope; mutable review state,
    # assignments and comments are intentionally excluded.
    item_evidence_digest = checksums.get("item_evidence_sha256")
    if item_evidence_digest is not None and (
        not isinstance(item_evidence_digest, str)
        or len(item_evidence_digest) != 64
        or any(char not in "0123456789abcdef" for char in item_evidence_digest)
        or item_evidence_digest != queue_item_evidence_sha256(items)
    ):
        raise invalid
