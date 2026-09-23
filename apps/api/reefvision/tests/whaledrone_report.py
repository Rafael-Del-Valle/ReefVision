"""Developer-only WhaleDrone normalization and generated diagnostic artifacts."""

import csv
import json
from collections import Counter
from math import hypot, isfinite
from pathlib import Path
from statistics import mean, median, pstdev

import numpy as np
from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.geodesy import geodesic_distance_m
from reefvision.geospatial.projection import SurfaceReference, project_pixel_to_local_surface
from reefvision.geospatial.validation import (
    GeoreferenceValidationPoint,
    GeoreferenceValidationReport,
    summarize_errors,
)
from reefvision.tests.whaledrone_georeferencing import WhaleDroneValidationClip, _basename

ROW_FIELDS = (
    "annotation_id",
    "video",
    "frame_index",
    "video_time_s",
    "annotation_video_time_s",
    "source_frame_number",
    "source_time_value",
    "object_id",
    "class_name",
    "pixel_x",
    "pixel_y",
    "telemetry_time_s",
    "sync_delta_s",
    "sync_error_s",
    "drone_latitude",
    "drone_longitude",
    "relative_altitude_m",
    "camera_height_m",
    "gimbal_yaw_deg",
    "gimbal_pitch_deg",
    "gimbal_roll_deg",
    "digital_zoom_ratio",
    "predicted_latitude",
    "predicted_longitude",
    "ground_truth_latitude",
    "ground_truth_longitude",
    "error_m",
    "east_error_m",
    "north_error_m",
    "distance_from_image_center_px",
    "exclusion_reason",
)


def _blank(value):
    return value is None or str(value).strip().casefold() in {"", "na", "nan"}


def load_annotations(
    clip: WhaleDroneValidationClip,
    *,
    frame_base: int | None,
    time_column: str | None = None,
    max_samples: int = 100,
):
    """Select source rows before predictions; retain every selected invalid row.

    time_column must only be supplied after establishing that it is relative
    seconds. The DVM `time` field is not implicitly assigned those semantics.
    """
    if frame_base is not None and (isinstance(frame_base, bool) or frame_base not in {0, 1}):
        raise ValidationError("A verified frame base of 0 or 1 is required")
    if frame_base is None and not time_column:
        raise ValidationError("A verified frame base or relative time column is required")
    if isinstance(max_samples, bool) or not isinstance(max_samples, int) or max_samples < 1:
        raise ValidationError("Sample limit must be a positive integer")
    with clip.annotation_path.open(encoding="utf-8-sig", newline="") as stream:
        all_rows = list(enumerate(csv.DictReader(stream), start=2))
    matching = [
        (i, row) for i, row in all_rows if _basename(row.get("video") or "") == clip.dvm_video_name
    ]
    if not matching:
        raise ValidationError("No annotations map to the selected video")
    # Source-order stratification is independent of pixels, telemetry, and GPS errors.
    selected = matching
    if len(matching) > max_samples:
        indices = np.linspace(0, len(matching) - 1, max_samples).round().astype(int)
        selected = [matching[int(i)] for i in indices]
    points, excluded = [], []
    for line, raw in selected:
        row = dict.fromkeys(ROW_FIELDS)
        row.update(
            annotation_id=f"{line}:{raw.get('name', '')}",
            video=clip.video_path.name,
            object_id=raw.get("name"),
            source_frame_number=raw.get("frame"),
            source_time_value=raw.get(time_column or "time"),
            pixel_x=raw.get("image_x"),
            pixel_y=raw.get("image_y"),
            ground_truth_latitude=raw.get("lat"),
            ground_truth_longitude=raw.get("lon"),
        )
        try:
            if None in raw or any(v is None for v in raw.values()):
                raise ValidationError("Malformed annotation row: wrong column count")
            if frame_base is not None and not _blank(raw.get("frame")):
                row["frame_index"] = int(raw["frame"]) - frame_base
            if time_column and not _blank(raw.get(time_column)):
                row["annotation_video_time_s"] = float(raw[time_column])
                row["video_time_s"] = row["annotation_video_time_s"]
            if not _blank(raw.get("length")):
                raise ValidationError("Unsupported vector geographic reference point")
            if _blank(raw.get("lat")) or _blank(raw.get("lon")):
                raise ValidationError("Missing geographic ground truth")
            if _blank(raw.get("image_x")) or _blank(raw.get("image_y")):
                raise ValidationError("Missing annotation pixel")
            point = GeoreferenceValidationPoint(
                point_id=row["annotation_id"],
                source_video=clip.video_path.name,
                frame_index=row["frame_index"],
                video_time_s=row["annotation_video_time_s"],
                pixel_x=float(raw["image_x"]),
                pixel_y=float(raw["image_y"]),
                latitude=float(raw["lat"]),
                longitude=float(raw["lon"]),
                object_id=raw.get("name"),
                source_frame_number=raw.get("frame"),
                source_time_value=raw.get(time_column or "time"),
                reference_height_m=None if _blank(raw.get("height")) else float(raw["height"]),
                reference_pitch_deg=None if _blank(raw.get("pitch")) else float(raw["pitch"]),
            )
            points.append(point)
        except (ValidationError, ValueError, TypeError, SchemaError) as exc:
            row["exclusion_reason"] = str(exc)
            excluded.append(row)
    return (
        points,
        excluded,
        {
            "matching_source_rows": len(matching),
            "selected_rows": len(selected),
            "unselected_by_prespecified_limit": len(matching) - len(selected),
            "other_video_rows": len(all_rows) - len(matching),
            "selection_rule": "Evenly spaced source rows before predictions",
            "sample_limit": max_samples,
            "pixel_definition": "DVM native point image_x/image_y; vector rows excluded",
            "column_mapping": {
                "video": "video via dataset index",
                "frame_index": "frame minus frame_base",
                "video_time_s": time_column,
                "pixel_x": "image_x",
                "pixel_y": "image_y",
                "latitude_gt": "lat",
                "longitude_gt": "lon",
                "object_id": "name",
            },
        },
    )


def observation_rows(report: GeoreferenceValidationReport):
    rows = []
    for observation in report.observations:
        point, sample, result = observation.point, observation.telemetry, observation.result
        row = dict.fromkeys(ROW_FIELDS)
        row.update(
            annotation_id=point.point_id,
            video=point.source_video,
            frame_index=point.frame_index,
            video_time_s=observation.video_time_s,
            annotation_video_time_s=point.video_time_s,
            source_frame_number=point.source_frame_number,
            source_time_value=point.source_time_value,
            object_id=point.object_id,
            class_name=point.class_name,
            pixel_x=point.pixel_x,
            pixel_y=point.pixel_y,
            ground_truth_latitude=point.latitude,
            ground_truth_longitude=point.longitude,
            sync_delta_s=observation.sync_delta_s,
            sync_error_s=observation.sync_error_s,
            error_m=observation.error_m,
            east_error_m=observation.east_error_m,
            north_error_m=observation.north_error_m,
            distance_from_image_center_px=observation.distance_from_image_center_px,
            exclusion_reason=observation.error,
        )
        if sample is not None:
            row.update(
                telemetry_time_s=sample.time_s,
                drone_latitude=sample.latitude,
                drone_longitude=sample.longitude,
                relative_altitude_m=sample.relative_altitude_m,
                gimbal_yaw_deg=sample.gimbal_yaw_deg,
                gimbal_pitch_deg=sample.gimbal_pitch_deg,
                gimbal_roll_deg=sample.gimbal_roll_deg,
                digital_zoom_ratio=sample.digital_zoom_ratio,
            )
        if result is not None:
            row.update(
                predicted_latitude=result.latitude,
                predicted_longitude=result.longitude,
                camera_height_m=result.camera_height_m,
            )
        rows.append(row)
    return rows


def _percentile(values):
    return float(np.percentile(values, 95, method="linear")) if values else None


def finalize_rows(report, excluded, *, fps):
    rows = observation_rows(report) + excluded
    for row in rows:
        if row["frame_index"] is not None:
            row["video_time_s"] = row["frame_index"] / fps
    return rows


def _sync_statistics(rows):
    signed = [row["sync_delta_s"] * 1000 for row in rows if row["sync_delta_s"] is not None]
    absolute = [abs(value) for value in signed]
    return {
        "sample_count": len(signed),
        "mean_sync_error_ms": mean(absolute) if absolute else None,
        "median_sync_error_ms": median(absolute) if absolute else None,
        "max_sync_error_ms": max(absolute) if absolute else None,
        "p95_sync_error_ms": _percentile(absolute),
        "mean_signed_sync_delta_ms": mean(signed) if signed else None,
    }


def _diagnostic(rows, field):
    pairs = [(row[field], row["error_m"]) for row in rows if row[field] is not None]
    x, y = [p[0] for p in pairs], [p[1] for p in pairs]
    r = None
    if len(pairs) >= 3 and max(x) > min(x) and max(y) > min(y):
        value = float(np.corrcoef(x, y)[0, 1])
        r = value if isfinite(value) else None
    return {
        "n": len(pairs),
        "pearson_r": r,
        "predictor_min": min(x) if x else None,
        "predictor_max": max(x) if x else None,
        "note": "Descriptive only; null for <3 pairs or zero variance. Small samples inconclusive.",
    }


def build_summary(rows, metadata):
    successful = [row for row in rows if not row["exclusion_reason"] and row["error_m"] is not None]
    excluded = [row for row in rows if row not in successful]
    statistics = summarize_errors([row["error_m"] for row in successful])
    summary = dict(metadata)
    summary.update(
        attempted=len(rows),
        projected=len(successful),
        excluded=len(excluded),
        label="PRELIMINARY VALIDATION" if len(successful) < 20 else "SINGLE-CLIP VALIDATION",
        operationally_projected=bool(successful),
        exclusion_counts=dict(
            Counter(row["exclusion_reason"] or "No projection" for row in excluded)
        ),
        std_convention="population (ddof=0)",
        percentile_convention="NumPy linear (Hyndman-Fan type 7)",
        directional_convention="WGS84 geodesic GT-to-prediction vector in local true East/North",
        reference_kind="DVM derived coordinates; not independently surveyed ground truth",
        accuracy_category=None,
        global_convention_corrections=[],
    )
    for output, field in (
        ("mean", "mean_m"),
        ("median", "median_m"),
        ("rmse", "rmse_m"),
        ("std", "std_m"),
        ("min", "min_m"),
        ("max", "max_m"),
        ("p95", "p95_m"),
    ):
        summary[f"{output}_error_m"] = getattr(statistics, field) if statistics else None
    for direction in ("east", "north"):
        values = [row[f"{direction}_error_m"] for row in successful]
        for label, operation in (("mean", mean), ("median", median), ("std", pstdev)):
            summary[f"{label}_{direction}_error_m"] = operation(values) if values else None
    primary_sync = _sync_statistics(successful)
    summary.update({key: value for key, value in primary_sync.items() if key != "sample_count"})
    summary["primary_sync_sample_count"] = primary_sync["sample_count"]
    summary["all_matched_sync"] = _sync_statistics(rows)
    summary["diagnostics"] = {
        field: _diagnostic(successful, field)
        for field in (
            "relative_altitude_m",
            "camera_height_m",
            "distance_from_image_center_px",
            "gimbal_pitch_deg",
            "sync_error_s",
        )
    }
    return summary


def sanity_checks(report, calibration):
    """Geometry-only checks on actual matched poses; no reference GPS is used."""
    distances, nadir, failures, seen = [], [], [], set()
    for observation in report.observations:
        sample, result = observation.telemetry, observation.result
        if observation.error or sample is None or result is None:
            continue
        distance = geodesic_distance_m(
            sample.latitude, sample.longitude, result.latitude, result.longitude
        )
        distances.append(distance)
        if distance > 10000 + 1e-6:
            failures.append("Prediction exceeds 10 km local projection guard")
        if sample.sample_index in seen or abs(sample.gimbal_pitch_deg + 90) > 1:
            continue
        seen.add(sample.sample_index)
        surface = SurfaceReference(
            camera_height_m=result.camera_height_m,
            evidence="Resolved height from evaluated observation",
        )
        cx, cy = calibration.width_px / 2, calibration.height_px / 2
        step = calibration.width_px * 0.05
        try:
            center, left, right = [
                project_pixel_to_local_surface(x, cy, calibration, sample, surface)
                for x in (cx, cx - step, cx + step)
            ]
            dot = sum((left[i] - center[i]) * (right[i] - center[i]) for i in (0, 1))
            if dot >= 0:
                failures.append("Opposite native pixels do not span the center footprint")
            nadir.append(
                {
                    "telemetry_sample_index": sample.sample_index,
                    "pitch_deg": sample.gimbal_pitch_deg,
                    "native_center_distance_m": hypot(*center),
                    "camera_height_m": result.camera_height_m,
                    "opposite_pixel_offset_dot_m2": dot,
                }
            )
        except ValidationError as exc:
            failures.append(str(exc))
    return {
        "passed": bool(distances) and not failures,
        "evaluated_projection_count": len(distances),
        "status": "evaluated" if distances else "not evaluated",
        "failures": failures,
        "near_nadir_definition": "absolute pitch difference from -90 degrees <=1 degree",
        "near_nadir_samples_checked": len(nadir),
        "near_nadir_checks": nadir,
        "max_target_distance_from_drone_m": max(distances) if distances else None,
        "distance_guard_m": 10000,
        "note": "Geometry sanity only; no center check without near-nadir samples. Not accuracy.",
    }


def write_report(directory: Path, rows, summary):
    """Write only generated reports; callers must not select the dataset directory."""
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "whaledrone_validation.csv"
    json_path = directory / "whaledrone_validation_summary.json"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return csv_path, json_path
