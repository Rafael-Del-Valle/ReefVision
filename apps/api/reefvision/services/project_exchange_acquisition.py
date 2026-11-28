"""Validate portable acquisition QC evidence and links before archive import."""

from math import isfinite
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.schemas.quality_control import AcquisitionQualityThresholds
from reefvision.services.acquisition_quality import METHOD
from reefvision.storage.datasets import canonical_json_sha256


def validate_acquisition_exchange(sections: dict[str, list[dict[str, Any]]]) -> None:
    images = {row["sha256"]: row for row in sections.get("images", [])}
    versions: dict[str, set[str]] = {}
    for row in sections.get("dataset_version_items", []):
        versions.setdefault(row["dataset_version_id"], set()).add(row["image_sha256"])
    results: dict[str, dict[str, Any]] = {}
    for run in sections.get("quality_control_runs", []):
        summary = run.get("summary_json") or {}
        report = summary.get("acquisition")
        if report is None:
            continue
        _validate_report(report)
        expected_sources = versions.get(run["dataset_version_id"], set())
        seen: set[str] = set()
        for image in report["images"]:
            digest = image["source_sha256"]
            metadata = {
                key: image[key]
                for key in (
                    "camera_metadata",
                    "capture_time_utc",
                    "calibration_sha256",
                    "width_px",
                    "height_px",
                )
            }
            if (
                digest in seen
                or digest not in images
                or (run["dataset_version_id"] is not None and digest not in expected_sources)
                or canonical_json_sha256(metadata) != image["metadata_sha256"]
            ):
                raise ValidationError("Acquisition QC source evidence is inconsistent")
            seen.add(digest)
        if report["thresholds"] != run["thresholds_json"].get("acquisition") or report[
            "evidence_sha256"
        ] != run["input_checksums_json"].get("acquisition_evidence_sha256"):
            raise ValidationError("Acquisition QC run and report do not agree")
        results[run["id"]] = report
    for artifact in sections.get("workflow_artifacts", []):
        if artifact.get("data_type") == "acquisition_quality_result":
            payload = artifact["payload_json"]
            if results.get(payload.get("quality_control_run_id")) != payload.get("report"):
                raise ValidationError("Acquisition QC workflow result has no matching report")


def _validate_report(report: Any) -> None:
    if not isinstance(report, dict) or report.get("method") != METHOD:
        raise ValidationError("Unknown acquisition QC method")
    digest = report.get("evidence_sha256")
    if (
        canonical_json_sha256(
            {key: value for key, value in report.items() if key != "evidence_sha256"}
        )
        != digest
    ):
        raise ValidationError("Acquisition QC evidence checksum does not match")
    try:
        AcquisitionQualityThresholds.model_validate(report["thresholds"])
        rows = report["images"]
        if (
            report["review_status"] != "review_required"
            or report["evaluated_image_count"] != len(rows)
            or report["unavailable_image_count"]
            != sum(row["measurements"]["status"] != "measured" for row in rows)
        ):
            raise ValidationError("Invalid acquisition QC report counts or review state")
        for row in rows:
            signal = row["measurements"]
            partial = (signal["dark_fraction"], signal["bright_fraction"])
            if signal["status"] == "measured":
                if any(type(value) not in (float, int) or not 0 <= value <= 1 for value in partial):
                    raise ValidationError("Invalid acquisition clipping fractions")
                if sum(partial) > 1.0000001:
                    raise ValidationError("Acquisition clipping bands overlap")
                score = signal["sharpness"]
                if score is not None and (
                    type(score) not in (float, int) or not isfinite(score) or score < 0
                ):
                    raise ValidationError("Invalid acquisition detail score")
            elif any(value is not None for value in (*partial, signal["sharpness"])):
                raise ValidationError("Unavailable acquisition QC reports measured values")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Invalid acquisition QC structured evidence") from exc
