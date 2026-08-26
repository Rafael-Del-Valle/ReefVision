from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import Job, VideoAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.videos import Scientific3DCalibrationValidationRequest

JOB_TYPE = "video_metric_depth_3d"
MODEL_ESTIMATED_TIER = "model_estimated_metric"
CALIBRATED_TIER = "calibrated_metric"
VALIDATION_SCHEMA = "scientific-3d-calibration-validation-0001"
MIN_REFERENCE_SAMPLES = 5
MIN_DISTINCT_FRAMES = 3
MIN_REFERENCE_DEPTH_SPAN_M = 0.05

_FORBIDDEN_REFERENCE_SOURCE_TOKENS = (
    "depth anything",
    "video depth anything",
    "monocular",
    "model output",
    "model prediction",
    "reefvision depth",
)


def _validate_independent_source(source: str) -> str:
    cleaned = " ".join(source.split())
    if not cleaned:
        raise ValidationError("Independent reference source cannot be blank")
    normalized = cleaned.casefold().replace("_", " ").replace("-", " ")
    if any(token in normalized for token in _FORBIDDEN_REFERENCE_SOURCE_TOKENS):
        raise ValidationError(
            "Calibration validation evidence must be independent of ReefVision "
            "monocular/model depth output"
        )
    return cleaned


def evaluate_depth_validation(
    *,
    predicted_depths: dict[tuple[str, int], float],
    references: list[tuple[str, int, float]],
    relative_tolerance: float,
    absolute_tolerance_m: float,
) -> dict[str, Any]:
    if len(references) < MIN_REFERENCE_SAMPLES:
        raise ValidationError(
            f"Scientific 3D calibration requires at least {MIN_REFERENCE_SAMPLES} "
            "independent reference samples"
        )

    rows: list[dict[str, Any]] = []
    unique_frames: set[int] = set()
    expected_depths: list[float] = []

    for track_id, frame, expected_depth_m in references:
        key = (track_id, frame)
        if key not in predicted_depths:
            raise ValidationError(
                "Independent reference does not match a reconstructed Scientific 3D "
                f"track/frame sample: track={track_id}, frame={frame}"
            )
        predicted_depth_m = float(predicted_depths[key])
        expected = float(expected_depth_m)
        if (
            not math.isfinite(predicted_depth_m)
            or predicted_depth_m <= 0
            or not math.isfinite(expected)
            or expected <= 0
        ):
            raise ValidationError("Calibration validation depths must be finite and positive")

        absolute_error_m = abs(predicted_depth_m - expected)
        relative_error = absolute_error_m / expected
        allowed_error_m = max(
            absolute_tolerance_m,
            expected * relative_tolerance,
        )
        rows.append(
            {
                "track_id": track_id,
                "frame": frame,
                "predicted_depth_m": predicted_depth_m,
                "expected_depth_m": expected,
                "absolute_error_m": absolute_error_m,
                "relative_error": relative_error,
                "allowed_error_m": allowed_error_m,
                "within_tolerance": absolute_error_m <= allowed_error_m,
            }
        )
        unique_frames.add(frame)
        expected_depths.append(expected)

    distinct_frames = len(unique_frames)
    reference_depth_span_m = max(expected_depths) - min(expected_depths)
    absolute_errors = [float(row["absolute_error_m"]) for row in rows]
    relative_errors = [float(row["relative_error"]) for row in rows]
    signed_errors = [
        float(row["predicted_depth_m"]) - float(row["expected_depth_m"]) for row in rows
    ]
    rmse_m = math.sqrt(sum(error * error for error in signed_errors) / len(signed_errors))
    all_within_tolerance = all(bool(row["within_tolerance"]) for row in rows)

    coverage_qualified = (
        distinct_frames >= MIN_DISTINCT_FRAMES
        and reference_depth_span_m >= MIN_REFERENCE_DEPTH_SPAN_M
    )
    qualified = all_within_tolerance and coverage_qualified

    return {
        "sample_count": len(rows),
        "distinct_frame_count": distinct_frames,
        "reference_depth_span_m": reference_depth_span_m,
        "mean_absolute_error_m": sum(absolute_errors) / len(absolute_errors),
        "mean_relative_error": sum(relative_errors) / len(relative_errors),
        "maximum_relative_error": max(relative_errors),
        "rmse_m": rmse_m,
        "mean_signed_error_m": sum(signed_errors) / len(signed_errors),
        "all_samples_within_tolerance": all_within_tolerance,
        "coverage_qualified": coverage_qualified,
        "qualified": qualified,
        "observations": rows,
    }


class Scientific3DCalibrationValidationService:
    def __init__(self, session: Session):
        self.session = session

    def validate(
        self,
        video_id: str,
        job_id: str,
        payload: Scientific3DCalibrationValidationRequest,
    ) -> dict[str, Any]:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")

        job = self.session.get(Job, job_id)
        if job is None or job.project_id != video.project_id or job.job_type != JOB_TYPE:
            raise NotFoundError("Scientific 3D job not found for this video")
        if job.status != "succeeded":
            raise ValidationError("Scientific 3D calibration validation requires a succeeded job")

        result = dict(job.result_json or {})
        if result.get("video_id") != video_id:
            raise ValidationError("Scientific 3D job result does not belong to this video")
        if result.get("depth_tier") not in {
            MODEL_ESTIMATED_TIER,
            CALIBRATED_TIER,
        }:
            raise ValidationError(
                "Only automatic metric Video Depth Anything jobs can be validated"
            )

        source = _validate_independent_source(payload.reference_source)

        analytics = result.get("analytics")
        if not isinstance(analytics, dict):
            raise ValidationError("Scientific 3D job result is missing reconstructed analytics")
        raw_tracks = analytics.get("tracks")
        if not isinstance(raw_tracks, list):
            raise ValidationError("Scientific 3D job result is missing reconstructed tracks")

        predicted_depths: dict[tuple[str, int], float] = {}
        for raw_track in raw_tracks:
            if not isinstance(raw_track, dict):
                continue
            track_id = str(raw_track.get("track_id", ""))
            raw_points = raw_track.get("points")
            if not track_id or not isinstance(raw_points, list):
                continue
            for raw_point in raw_points:
                if not isinstance(raw_point, dict):
                    continue
                try:
                    frame = int(raw_point["frame"])
                    depth = float(raw_point["z"])
                except (KeyError, TypeError, ValueError):
                    continue
                predicted_depths[(track_id, frame)] = depth

        references = [
            (sample.track_id, sample.frame, float(sample.expected_depth_m))
            for sample in payload.reference_samples
        ]
        evaluation = evaluate_depth_validation(
            predicted_depths=predicted_depths,
            references=references,
            relative_tolerance=float(payload.relative_tolerance),
            absolute_tolerance_m=float(payload.absolute_tolerance_m),
        )

        qualified = bool(evaluation["qualified"])
        validation = {
            "schema_version": VALIDATION_SCHEMA,
            "validated_at": datetime.now(UTC).isoformat(),
            "video_id": video_id,
            "job_id": job_id,
            "reference_source": source,
            "reference_method": payload.reference_method,
            "setup_description": payload.setup_description,
            "notes": payload.notes,
            "environment": "underwater",
            "independent_reference_confirmed": True,
            "same_optical_setup_confirmed": True,
            "underwater_environment_confirmed": True,
            "relative_tolerance": float(payload.relative_tolerance),
            "absolute_tolerance_m": float(payload.absolute_tolerance_m),
            "minimum_requirements": {
                "sample_count": MIN_REFERENCE_SAMPLES,
                "distinct_frame_count": MIN_DISTINCT_FRAMES,
                "reference_depth_span_m": MIN_REFERENCE_DEPTH_SPAN_M,
            },
            "depth_correction_applied": False,
            "raw_model_depth_validated": True,
            **evaluation,
        }

        result["calibration_validation"] = validation
        provenance = dict(result.get("scientific_provenance") or {})
        provenance["calibration_validation"] = {
            "schema_version": VALIDATION_SCHEMA,
            "validated_at": validation["validated_at"],
            "qualified": qualified,
            "reference_source": source,
            "reference_method": payload.reference_method,
            "sample_count": evaluation["sample_count"],
            "distinct_frame_count": evaluation["distinct_frame_count"],
            "reference_depth_span_m": evaluation["reference_depth_span_m"],
            "relative_tolerance": float(payload.relative_tolerance),
            "absolute_tolerance_m": float(payload.absolute_tolerance_m),
            "depth_correction_applied": False,
        }
        result["scientific_provenance"] = provenance

        if qualified:
            result["depth_tier"] = CALIBRATED_TIER
            result["physical_measurement_claim_allowed"] = True
            result["underwater_validation_required"] = False
        else:
            result["depth_tier"] = MODEL_ESTIMATED_TIER
            result["physical_measurement_claim_allowed"] = False
            result["underwater_validation_required"] = True

        job.result_json = result
        self.session.commit()
        self.session.refresh(job)
        return dict(job.result_json or {})
