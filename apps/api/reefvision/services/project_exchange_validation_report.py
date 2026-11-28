"""Check archived validation reports against their frozen inputs and event details."""

from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.domain.reefpose_agreement import rate
from reefvision.storage.datasets import canonical_json_sha256

_MANIFEST_FIELDS = (
    "schema_version",
    "reference_id",
    "reference_sha256",
    "scored_reference_manifest",
    "data_kind",
    "split",
    "rater_id",
    "models",
    "prediction_sources",
    "tracker_protocol",
    "development_lock_sha256",
    "configurations",
    "bootstrap_seed",
)
_COUNTS = ("tp", "fp", "fn")


def _event_counts(payload: dict[str, Any]) -> tuple[int, int, int]:
    tp, fp, fn = (payload[key] for key in _COUNTS)
    if any(type(count) is not int or count < 0 for count in (tp, fp, fn)):
        raise ValidationError("Exchange ReefPose event counts are invalid")
    expected = {
        "precision": rate(tp, tp + fp),
        "recall": rate(tp, tp + fn),
        "f1": rate(2 * tp, 2 * tp + fp + fn),
        "count_error": fp - fn,
    }
    if any(payload[key] != value for key, value in expected.items()):
        raise ValidationError("Exchange ReefPose event metrics do not agree with their counts")
    return tp, fp, fn


def validate_reefpose_report(report: dict[str, Any], reference: dict[str, Any] | None) -> None:
    """Verify scientific consistency without comparing against mutable current evidence."""
    manifest = {key: report[key] for key in _MANIFEST_FIELDS}
    if canonical_json_sha256(manifest) != report["input_sha256"]:
        raise ValidationError("Exchange ReefPose report input checksum does not match")
    if reference is None:
        raise ValidationError("Exchange ReefPose report has no frozen reference")
    frozen = reference["manifest"]
    recordings = [row for row in frozen["recordings"] if row["split"] == report["split"]]
    if (
        reference["manifest_sha256"] != report["reference_sha256"]
        or reference["data_kind"] != report["data_kind"]
        or {**frozen, "recordings": recordings} != report["scored_reference_manifest"]
    ):
        raise ValidationError("Exchange ReefPose report does not match its frozen reference")
    configurations = report["configurations"]
    selected = report["selected_configuration_index"]
    sensitivity = report["sensitivity"]
    if (
        type(selected) is not int
        or not 0 <= selected < len(configurations)
        or report["selected_configuration"] != configurations[selected]
        or len(sensitivity) != len(configurations)
        or [row["configuration_index"] for row in sensitivity] != list(range(len(configurations)))
    ):
        raise ValidationError("Exchange ReefPose report has inconsistent configuration results")
    scored = {recording["video_id"] for recording in recordings}
    sources = [source["video_id"] for source in report["prediction_sources"]]
    results = [recording["video_id"] for recording in report["recordings"]]
    if not scored or sorted(sources) != sorted(scored) or sorted(results) != sorted(scored):
        raise ValidationError("Exchange ReefPose report recordings do not match its frozen inputs")
    windows = [
        event
        for recording in report["recordings"]
        for event in recording["events"]
        if "excluded" not in event
    ]
    for state in ("complete", "partial"):
        alternatives = [_event_counts(row[state]) for row in sensitivity]
        observed = []
        for window in windows:
            result = window[state]
            counts = _event_counts(result)
            if counts != (len(result["matches"]), len(result["spurious"]), len(result["missed"])):
                raise ValidationError("Exchange ReefPose event counts do not match saved details")
            observed.append(counts)
        totals = tuple(sum(row[index] for row in observed) for index in range(len(_COUNTS)))
        if totals != alternatives[selected]:
            raise ValidationError("Exchange ReefPose event counts do not match recording totals")
