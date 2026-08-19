"""Validate ReefVision 2D scale and metric-depth analytics against known measurements.

This harness is intentionally separate from the future automatic ruler/marker calibration
feature. The caller supplies a real calibration video and an independently measured JSON
reference file. ReefVision stores the known-length spatial calibration, evaluates a
verified track in physical units, stores independently obtained camera intrinsics, and
runs metric-depth 3D trajectory analytics. The reported physical results are compared to
external expected values using explicit tolerances and verified again after restart.

Relative monocular Depth Anything output is not accepted as metric depth input here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.main import create_app

SCHEMA_VERSION = "reefvision-physical-calibration-validation-0001"
SUPPORTED_UNITS = {"mm", "cm", "m"}


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"API {response.request.method} {response.url}: {response.text}")
    return dict(response.json())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_float(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result <= 0:
        raise RuntimeError(f"{name} must be finite and positive")
    return result


def _finite_float(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"{name} must be finite")
    return result


def load_reference(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Calibration reference JSON could not be read: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Reference must use schema_version {SCHEMA_VERSION!r}")

    spatial = payload.get("spatial_reference")
    track = payload.get("track")
    intrinsics = payload.get("camera_intrinsics")
    metric_depth = payload.get("metric_depth")
    if not all(isinstance(value, dict) for value in (spatial, track, intrinsics, metric_depth)):
        raise RuntimeError(
            "Reference must define spatial_reference, track, camera_intrinsics, and metric_depth"
        )
    spatial = dict(spatial)
    track = dict(track)
    intrinsics = dict(intrinsics)
    metric_depth = dict(metric_depth)

    spatial_unit = str(spatial.get("unit", ""))
    depth_unit = str(metric_depth.get("unit", ""))
    if spatial_unit not in SUPPORTED_UNITS or depth_unit not in SUPPORTED_UNITS:
        raise RuntimeError("Calibration units must be one of mm, cm, or m")
    spatial["reference_distance"] = _positive_float(
        spatial.get("reference_distance"), name="spatial_reference.reference_distance"
    )
    spatial["reference_pixels"] = _positive_float(
        spatial.get("reference_pixels"), name="spatial_reference.reference_pixels"
    )

    class_name = str(track.get("class_name", "Calibration target")).strip()
    if not class_name:
        raise RuntimeError("track.class_name cannot be blank")
    track["class_name"] = class_name
    raw_keyframes = track.get("keyframes")
    if not isinstance(raw_keyframes, list) or len(raw_keyframes) < 2:
        raise RuntimeError("track.keyframes requires at least two observations")
    keyframes: list[dict[str, Any]] = []
    previous_frame = -1
    for raw in raw_keyframes:
        if not isinstance(raw, dict):
            raise RuntimeError("track.keyframes entries must be objects")
        try:
            frame = int(raw.get("frame"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("track keyframe frame must be an integer") from exc
        bbox = raw.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise RuntimeError("track keyframe bbox must contain [x, y, width, height]")
        values = [_finite_float(value, name="track bbox value") for value in bbox]
        if frame < 0 or frame <= previous_frame or values[0] < 0 or values[1] < 0:
            raise RuntimeError("Track frames must ascend and bbox origins must be nonnegative")
        if values[2] <= 0 or values[3] <= 0:
            raise RuntimeError("Track bbox width/height must be positive")
        previous_frame = frame
        keyframes.append({"frame": frame, "bbox": values})
    track["keyframes"] = keyframes

    expected_2d = track.get("expected_2d")
    if not isinstance(expected_2d, dict):
        raise RuntimeError("track.expected_2d is required")
    for key in ("path_length", "displacement", "mean_speed_per_second"):
        expected_2d[key] = _positive_float(expected_2d.get(key), name=f"expected_2d.{key}")
    if expected_2d.get("maximum_speed_per_second") is not None:
        expected_2d["maximum_speed_per_second"] = _positive_float(
            expected_2d["maximum_speed_per_second"],
            name="expected_2d.maximum_speed_per_second",
        )

    for key in ("fx_px", "fy_px"):
        intrinsics[key] = _positive_float(intrinsics.get(key), name=f"camera_intrinsics.{key}")
    for key in ("cx_px", "cy_px"):
        intrinsics[key] = _finite_float(intrinsics.get(key), name=f"camera_intrinsics.{key}")

    samples = metric_depth.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        raise RuntimeError("metric_depth.samples requires at least two metric depth samples")
    normalized_samples: list[dict[str, Any]] = []
    seen_frames: set[int] = set()
    for raw in samples:
        if not isinstance(raw, dict):
            raise RuntimeError("metric_depth sample must be an object")
        try:
            frame = int(raw.get("frame"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("metric_depth sample frame must be an integer") from exc
        if frame < 0 or frame in seen_frames:
            raise RuntimeError("metric_depth sample frames must be unique and nonnegative")
        seen_frames.add(frame)
        sample = {
            "frame": frame,
            "depth": _positive_float(raw.get("depth"), name="metric_depth.sample.depth"),
        }
        if raw.get("confidence") is not None:
            confidence = _finite_float(
                raw.get("confidence"), name="metric_depth.sample.confidence"
            )
            if not 0 <= confidence <= 1:
                raise RuntimeError("metric depth confidence must be between 0 and 1")
            sample["confidence"] = confidence
        normalized_samples.append(sample)
    metric_depth["samples"] = sorted(normalized_samples, key=lambda item: item["frame"])

    expected_3d = metric_depth.get("expected_3d")
    if not isinstance(expected_3d, dict):
        raise RuntimeError("metric_depth.expected_3d is required")
    for key in ("path_length_3d", "displacement_3d", "mean_speed_3d_per_second", "mean_depth"):
        expected_3d[key] = _positive_float(expected_3d.get(key), name=f"expected_3d.{key}")

    tolerance = payload.get("tolerance", {})
    if not isinstance(tolerance, dict):
        raise RuntimeError("tolerance must be an object")
    relative = _finite_float(tolerance.get("relative", 0.02), name="tolerance.relative")
    absolute = _finite_float(tolerance.get("absolute", 0.0), name="tolerance.absolute")
    if relative < 0 or absolute < 0:
        raise RuntimeError("Tolerances cannot be negative")

    return {
        "schema_version": SCHEMA_VERSION,
        "video_sha256": (
            str(payload["video_sha256"]).strip().casefold()
            if payload.get("video_sha256")
            else None
        ),
        "spatial_reference": spatial,
        "track": track,
        "camera_intrinsics": intrinsics,
        "metric_depth": metric_depth,
        "tolerance": {"relative": relative, "absolute": absolute},
        "notes": str(payload.get("notes", "")).strip() or None,
    }


def measurement_error(
    observed: float, expected: float, *, relative_tolerance: float, absolute_tolerance: float
) -> dict[str, Any]:
    absolute_error = abs(observed - expected)
    relative_error = absolute_error / abs(expected) if expected != 0 else math.inf
    within = absolute_error <= max(absolute_tolerance, abs(expected) * relative_tolerance)
    return {
        "observed": observed,
        "expected": expected,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "within_tolerance": within,
    }


def _compare_mapping(
    observed: dict[str, Any],
    expected: dict[str, Any],
    keys: tuple[str, ...],
    *,
    relative_tolerance: float,
    absolute_tolerance: float,
) -> dict[str, dict[str, Any]]:
    return {
        key: measurement_error(
            float(observed[key]),
            float(expected[key]),
            relative_tolerance=relative_tolerance,
            absolute_tolerance=absolute_tolerance,
        )
        for key in keys
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()

    video_path = args.video.resolve()
    reference_path = args.reference.resolve()
    output = args.output.resolve()
    state = args.state.resolve() if args.state else output / "reefvision-data"
    for path in (video_path, reference_path):
        if not path.is_file():
            raise RuntimeError(f"Required calibration input does not exist: {path}")
    if output.exists():
        raise RuntimeError(f"Acceptance output already exists: {output}")
    output.mkdir(parents=True)
    state.mkdir(parents=True, exist_ok=False)

    reference = load_reference(reference_path)
    video_hash = sha256(video_path)
    if reference["video_sha256"] and reference["video_sha256"] != video_hash:
        raise RuntimeError("Reference video_sha256 does not match the supplied video")

    settings = Settings(
        env="acceptance",
        data_dir=state,
        database_url=f"sqlite:///{(state / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    started = time.perf_counter()

    with TestClient(app) as client:
        project = require(
            client.post(
                "/api/v1/projects",
                json={"name": "Physical calibration validation", "template": "blank"},
            ),
            201,
        )
        label = require(
            client.post(
                f"/api/v1/projects/{project['id']}/classes",
                json={
                    "class_index": 0,
                    "display_order": 0,
                    "name": reference["track"]["class_name"],
                    "description": "Known physical calibration target",
                    "display_color": "#4C9A8A",
                },
            ),
            201,
        )
        video = require(
            client.post(
                f"/api/v1/projects/{project['id']}/imports/videos",
                files={
                    "file": (
                        video_path.name,
                        video_path.read_bytes(),
                        "video/mp4",
                    )
                },
            ),
            201,
        )
        if video["sha256"] != video_hash:
            raise RuntimeError("Managed video checksum differs from source video")
        if reference["track"]["keyframes"][-1]["frame"] >= int(video["frame_count"]):
            raise RuntimeError("Reference track uses a frame outside the source video")

        track = require(
            client.post(
                f"/api/v1/videos/{video['id']}/tracks",
                json={
                    "label_class_id": label["id"],
                    "track_number": 1,
                    "geometry_kind": "bbox",
                    "keyframes": reference["track"]["keyframes"],
                    "interpolation": "linear",
                    "status": "verified",
                },
            ),
            201,
        )
        spatial = reference["spatial_reference"]
        calibration = require(
            client.put(
                f"/api/v1/videos/{video['id']}/calibration",
                json={
                    "unit": spatial["unit"],
                    "reference_distance": spatial["reference_distance"],
                    "reference_pixels": spatial["reference_pixels"],
                    "method": "independently_measured_known_length",
                    "reference_label": str(spatial.get("reference_label", "known reference")),
                    "notes": reference.get("notes"),
                },
            ),
            200,
        )
        calibrated = require(
            client.get(f"/api/v1/video-tracks/{track['id']}/calibrated-analytics"), 200
        )

        intrinsics = reference["camera_intrinsics"]
        stored_intrinsics = require(
            client.put(
                f"/api/v1/videos/{video['id']}/camera-intrinsics",
                json={
                    "fx_px": intrinsics["fx_px"],
                    "fy_px": intrinsics["fy_px"],
                    "cx_px": intrinsics["cx_px"],
                    "cy_px": intrinsics["cy_px"],
                    "method": str(intrinsics.get("method", "independent_camera_calibration")),
                    "notes": reference.get("notes"),
                },
            ),
            200,
        )
        depth = reference["metric_depth"]
        depth_payload = {
            "unit": depth["unit"],
            "samples": [
                {"track_id": track["id"], **sample} for sample in depth["samples"]
            ],
        }
        if depth.get("maximum_frame_gap") is not None:
            depth_payload["maximum_frame_gap"] = int(depth["maximum_frame_gap"])
        depth_analytics = require(
            client.post(
                f"/api/v1/videos/{video['id']}/depth-track-analytics",
                json=depth_payload,
            ),
            200,
        )
        if len(depth_analytics["tracks"]) != 1:
            raise RuntimeError("Metric-depth validation expected one analyzed track")
        depth_track = depth_analytics["tracks"][0]

    app.state.engine.dispose()

    tolerance = reference["tolerance"]
    comparisons_2d = _compare_mapping(
        calibrated,
        reference["track"]["expected_2d"],
        ("path_length", "displacement", "mean_speed_per_second"),
        relative_tolerance=tolerance["relative"],
        absolute_tolerance=tolerance["absolute"],
    )
    if reference["track"]["expected_2d"].get("maximum_speed_per_second") is not None:
        comparisons_2d["maximum_speed_per_second"] = measurement_error(
            float(calibrated["maximum_speed_per_second"]),
            float(reference["track"]["expected_2d"]["maximum_speed_per_second"]),
            relative_tolerance=tolerance["relative"],
            absolute_tolerance=tolerance["absolute"],
        )
    comparisons_3d = _compare_mapping(
        depth_track,
        reference["metric_depth"]["expected_3d"],
        ("path_length_3d", "displacement_3d", "mean_speed_3d_per_second", "mean_depth"),
        relative_tolerance=tolerance["relative"],
        absolute_tolerance=tolerance["absolute"],
    )

    restart_app = create_app(settings)
    restart_started = time.perf_counter()
    with TestClient(restart_app) as client:
        restart_calibration = require(
            client.get(f"/api/v1/videos/{video['id']}/calibration"), 200
        )
        restart_intrinsics = require(
            client.get(f"/api/v1/videos/{video['id']}/camera-intrinsics"), 200
        )
        restart_calibrated = require(
            client.get(f"/api/v1/video-tracks/{track['id']}/calibrated-analytics"), 200
        )
        restart_depth = require(
            client.post(
                f"/api/v1/videos/{video['id']}/depth-track-analytics",
                json=depth_payload,
            ),
            200,
        )
    restart_duration = time.perf_counter() - restart_started
    restart_app.state.engine.dispose()

    all_within = all(
        item["within_tolerance"]
        for group in (comparisons_2d, comparisons_3d)
        for item in group.values()
    )
    restart_stable = (
        restart_calibration["pixels_per_unit"] == calibration["pixels_per_unit"]
        and restart_intrinsics["fx_px"] == stored_intrinsics["fx_px"]
        and restart_intrinsics["fy_px"] == stored_intrinsics["fy_px"]
        and restart_calibrated["path_length"] == calibrated["path_length"]
        and restart_depth["tracks"][0]["path_length_3d"] == depth_track["path_length_3d"]
    )
    acceptance = "PASS" if all_within and restart_stable else "FAIL"
    report = {
        "acceptance": acceptance,
        "commit_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Physical known-length and independently calibrated metric-depth validation. "
            "Relative monocular depth is explicitly not accepted as metric evidence."
        ),
        "inputs": {
            "video": str(video_path),
            "video_sha256": video_hash,
            "reference": str(reference_path),
            "reference_sha256": sha256(reference_path),
            "tolerance": tolerance,
        },
        "reefvision": {
            "project_id": project["id"],
            "video_id": video["id"],
            "track_id": track["id"],
            "spatial_calibration": calibration,
            "camera_intrinsics": stored_intrinsics,
        },
        "two_dimensional_validation": {
            "analytics": calibrated,
            "expected": reference["track"]["expected_2d"],
            "comparisons": comparisons_2d,
        },
        "metric_depth_validation": {
            "relative_monocular_depth_is_metric": False,
            "analytics": depth_analytics,
            "expected": reference["metric_depth"]["expected_3d"],
            "comparisons": comparisons_3d,
        },
        "restart": {
            "passed": restart_stable,
            "duration_seconds": restart_duration,
        },
        "duration_seconds": time.perf_counter() - started,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if acceptance == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
