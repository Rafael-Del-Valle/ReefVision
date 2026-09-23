"""Informational comparison against external DVM-computed geography; no downloads."""

import json
from pathlib import Path
from statistics import median

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.projection import SurfaceReference
from reefvision.geospatial.validation import evaluate_georeferencing
from reefvision.services.video_assets import _inspect_video
from reefvision.storage.georeferencing import load_camera_calibration
from reefvision.storage.telemetry import load_dji_srt
from reefvision.tests.whaledrone import get_whaledrone_root
from reefvision.tests.whaledrone_georeferencing import select_validation_clip
from reefvision.tests.whaledrone_report import (
    ROW_FIELDS,
    build_summary,
    finalize_rows,
    load_annotations,
    sanity_checks,
    write_report,
)


@pytest.mark.integration
def test_external_whaledrone_georeferencing(request):
    if not request.config.getoption("--whaledrone-integration"):
        pytest.skip("Explicit --whaledrone-integration opt-in required")
    root = get_whaledrone_root()
    if root is None:
        pytest.skip("REEFVISION_WHALEDRONE_ROOT is unset, unavailable, or inside the repository")
    frame_base = request.config.getoption("--whaledrone-frame-base")
    height_offset = request.config.getoption("--whaledrone-takeoff-height-m")
    height_verified = request.config.getoption("--whaledrone-height-datum-verified")
    evidence = request.config.getoption("--whaledrone-height-evidence")
    time_column = request.config.getoption("--whaledrone-time-column")
    if (frame_base is None and time_column is None) or height_offset is None or not evidence:
        pytest.skip(
            "Real projection requires verified frame-base, "
            "takeoff-to-surface height, and evidence options"
        )
    sync_evidence = request.config.getoption("--whaledrone-sync-evidence")
    camera_evidence = request.config.getoption("--whaledrone-camera-evidence")
    if not sync_evidence or not camera_evidence:
        pytest.skip(
            "Verified synchronization convention and compatible camera mode evidence required"
        )
    calibration_path = root / "camera_calibration_DJIM3T_RGBwide.json"
    if not calibration_path.is_file():
        raise ValidationError("External camera calibration is unavailable")
    try:
        clip = select_validation_clip(
            root, video_name=request.config.getoption("--whaledrone-video")
        )
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    calibration = load_camera_calibration(calibration_path)
    metadata = _inspect_video(clip.video_path)
    assert (metadata["width_px"], metadata["height_px"]) == (
        calibration.width_px,
        calibration.height_px,
    )
    points, excluded, selection = load_annotations(
        clip,
        frame_base=frame_base,
        max_samples=100,
        time_column=time_column,
    )
    source = load_dji_srt(clip.srt_path)
    cadence = [
        b.time_s - a.time_s
        for a, b in zip(source.samples, source.samples[1:], strict=False)
        if b.time_s > a.time_s
    ]
    accepted = []
    for point in points:
        time_s = (
            point.frame_index / float(metadata["fps"])
            if point.frame_index is not None
            else point.video_time_s
        )
        if time_s is None or time_s >= metadata["frame_count"] / float(metadata["fps"]):
            excluded.append(dict.fromkeys(ROW_FIELDS))
            excluded[-1].update(
                annotation_id=point.point_id,
                video=point.source_video,
                frame_index=point.frame_index,
                video_time_s=time_s,
                annotation_video_time_s=point.video_time_s,
                source_frame_number=point.source_frame_number,
                source_time_value=point.source_time_value,
                object_id=point.object_id,
                class_name=point.class_name,
                pixel_x=point.pixel_x,
                pixel_y=point.pixel_y,
                ground_truth_latitude=point.latitude,
                ground_truth_longitude=point.longitude,
                exclusion_reason="Annotation outside video duration",
            )
        else:
            accepted.append(point)
    report = evaluate_georeferencing(
        points=accepted,
        telemetry_source=source,
        calibration=calibration,
        fps=float(metadata["fps"]),
        surface=SurfaceReference(
            takeoff_height_above_surface_m=height_offset,
            evidence=evidence,
        ),
        max_delta_s=0.100,
        video_time_offset_s=request.config.getoption("--whaledrone-time-offset-s"),
        time_offset_evidence=request.config.getoption("--whaledrone-time-offset-evidence"),
    )
    rows = finalize_rows(report, excluded, fps=float(metadata["fps"]))
    sanity = sanity_checks(report, calibration)
    summary = build_summary(
        rows,
        {
            "status": "RUN_COMPLETED" if height_verified else "CONDITIONAL_BASELINE_COMPLETED",
            "height_datum_verified": height_verified,
            "scientifically_validated": False,
            "sanity_checks": sanity,
            "external_root": str(root),
            "video": clip.video_path.name,
            "srt": clip.srt_path.name,
            "calibration": calibration_path.name,
            "calibration_source_id": calibration.source_id,
            "annotation": clip.annotation_path.name,
            "selection": selection,
            "frame_base": frame_base,
            "fps": metadata["fps"],
            "native_width_px": calibration.width_px,
            "native_height_px": calibration.height_px,
            "srt_sample_count": len(source.samples),
            "srt_cadence_median_s": median(cadence) if cadence else None,
            "srt_cadence_min_s": min(cadence) if cadence else None,
            "srt_cadence_max_s": max(cadence) if cadence else None,
            "sync_threshold_s": 0.100,
            "sync_evidence": sync_evidence,
            "camera_evidence": camera_evidence,
            "surface_evidence": evidence,
            "takeoff_height_above_surface_m": height_offset,
            "time_offset_s": request.config.getoption("--whaledrone-time-offset-s"),
            "time_offset_evidence": request.config.getoption("--whaledrone-time-offset-evidence"),
            "sync_method": "Documented frame/FPS preferred; documented relative seconds fallback",
            "sync_metric_scope": "Nearest-sample distance, not inter-source clock verification",
        },
    )
    destination = Path(__file__).resolve().parents[4] / ".artifacts" / "whaledrone-validation"
    assert not destination.resolve().is_relative_to(root.resolve())
    write_report(destination, rows, summary)
    print(json.dumps(summary, indent=2, allow_nan=False))
    assert summary["attempted"] == selection["selected_rows"]
    assert sanity["passed"], "Geometry sanity failed; inspect generated report"
    assert summary["projected"] > 0, "No projected points; inspect generated exclusion report"
