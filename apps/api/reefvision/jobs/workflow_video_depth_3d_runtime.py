"""Calibrated metric 3D video trajectories for the unified workflow measurement node.

The current ReefVision executor already routes measurement nodes through a configurable
scientific runtime. 3D video science is therefore implemented as a measurement mode rather
than introducing a second workflow executor. Relative monocular depth is never promoted to
physical distance: callers must declare a calibrated metric source and provide camera
intrinsics plus metric depth samples.
"""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import VideoAsset, VideoTrack, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs, workflow_science_runtime
from reefvision.services.video_tracks import interpolate_track, observation_center

_ORIGINAL_MEASUREMENTS = workflow_science_runtime._workflow_measurements
_ALLOWED_DEPTH_SOURCES = {
    "calibrated_metric",
    "imported_metric",
    "metric_rgbd",
    "metric_stereo",
}
_ALLOWED_UNITS = {"m", "cm", "mm"}


def _finite_positive(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise RuntimeError(f"{name} must be finite and greater than zero")
    return parsed


def _finite(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise RuntimeError(f"{name} must be finite")
    return parsed


def _camera_intrinsics(
    video: VideoAsset,
    configuration: dict[str, Any],
) -> dict[str, float]:
    raw = configuration.get("camera_intrinsics")
    if not isinstance(raw, dict):
        metadata = dict(video.metadata_json or {})
        candidate = metadata.get("camera_intrinsics")
        raw = candidate if isinstance(candidate, dict) else None
    if not isinstance(raw, dict):
        raise RuntimeError(
            "video_depth_3d measurement requires camera_intrinsics with fx, fy, cx, and cy"
        )
    fx = _finite_positive(raw.get("fx"), "camera_intrinsics.fx")
    fy = _finite_positive(raw.get("fy"), "camera_intrinsics.fy")
    cx = _finite(raw.get("cx"), "camera_intrinsics.cx")
    cy = _finite(raw.get("cy"), "camera_intrinsics.cy")
    if not 0 <= cx <= video.width_px or not 0 <= cy <= video.height_px:
        raise RuntimeError("Camera principal point must fall inside the source video frame")
    return {"fx": fx, "fy": fy, "cx": cx, "cy": cy}


def _track_lookup(
    session: Session,
    *,
    run: WorkflowRun,
    video: VideoAsset,
    requested_track_ids: list[str],
) -> tuple[dict[str, VideoTrack], dict[int, VideoTrack]]:
    query = select(VideoTrack).where(
        VideoTrack.video_id == video.id,
        VideoTrack.deleted_at.is_(None),
    )
    if requested_track_ids:
        query = query.where(VideoTrack.id.in_(requested_track_ids))
    tracks = list(session.scalars(query.order_by(VideoTrack.track_number, VideoTrack.id)))
    if requested_track_ids and len(tracks) != len(set(requested_track_ids)):
        raise RuntimeError("One or more 3D workflow tracks are missing from the selected video")
    if video.project_id != run.project_id:
        raise RuntimeError("3D workflow video does not belong to the workflow project")
    if not tracks:
        raise RuntimeError("video_depth_3d measurement requires at least one video track")
    return ({track.id: track for track in tracks}, {track.track_number: track for track in tracks})


def _resolve_track(
    sample: dict[str, Any],
    by_id: dict[str, VideoTrack],
    by_number: dict[int, VideoTrack],
    index: int,
) -> VideoTrack:
    track_id = sample.get("track_id")
    if isinstance(track_id, str) and track_id in by_id:
        return by_id[track_id]
    raw_number = sample.get("track_number")
    try:
        track_number = int(raw_number) if raw_number is not None else None
    except (TypeError, ValueError):
        track_number = None
    if track_number is not None and track_number in by_number:
        return by_number[track_number]
    raise RuntimeError(
        f"Depth sample {index} must reference a track_id or track_number from the tracks input"
    )


def _observation_center_at_frame(
    track: VideoTrack,
    video: VideoAsset,
    frame_index: int,
) -> tuple[float, float, float | None]:
    for observation in interpolate_track(track, video):
        if observation.frame_index == frame_index:
            center_x, center_y = observation_center(observation)
            return center_x, center_y, observation.timestamp_seconds
    raise RuntimeError(
        f"No track observation is available for track {track.track_number} at frame {frame_index}"
    )


def _back_project(
    center_x: float,
    center_y: float,
    depth: float,
    intrinsics: dict[str, float],
) -> tuple[float, float, float]:
    x = (center_x - intrinsics["cx"]) * depth / intrinsics["fx"]
    y = (center_y - intrinsics["cy"]) * depth / intrinsics["fy"]
    return x, y, depth


def _workflow_video_depth_3d(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    input_video_ids = workflow_runs._list_values(payloads, "video_ids")
    input_track_ids = workflow_runs._list_values(payloads, "track_ids")
    configured_video_id = str(configuration.get("video_id", "")).strip()
    video_ids = [configured_video_id] if configured_video_id else input_video_ids
    video_ids = list(dict.fromkeys(video_ids))
    if len(video_ids) != 1:
        raise RuntimeError("video_depth_3d measurement requires exactly one video")

    depth_source_kind = str(configuration.get("depth_source_kind", "")).strip().casefold()
    if depth_source_kind not in _ALLOWED_DEPTH_SOURCES:
        raise RuntimeError(
            "3D physical trajectories require calibrated metric depth from RGB-D, stereo, "
            "or an explicitly calibrated/imported metric source; relative monocular depth "
            "cannot be interpreted as physical distance"
        )
    unit = str(configuration.get("unit", "m")).strip().casefold()
    if unit not in _ALLOWED_UNITS:
        raise RuntimeError("3D trajectory unit must be one of m, cm, or mm")

    raw_samples = configuration.get("depth_samples")
    if not isinstance(raw_samples, list) or len(raw_samples) < 2:
        raise RuntimeError("video_depth_3d measurement requires at least two metric depth samples")

    maximum_frame_gap_raw = configuration.get("maximum_frame_gap")
    maximum_frame_gap = (
        int(maximum_frame_gap_raw) if maximum_frame_gap_raw is not None else None
    )
    if maximum_frame_gap is not None and maximum_frame_gap < 1:
        raise RuntimeError("maximum_frame_gap must be at least one frame")

    with factory() as session:
        video = session.get(VideoAsset, video_ids[0])
        if video is None:
            raise RuntimeError("3D workflow video no longer exists")
        intrinsics = _camera_intrinsics(video, configuration)
        by_id, by_number = _track_lookup(
            session,
            run=run,
            video=video,
            requested_track_ids=input_track_ids,
        )

        samples_by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for index, raw in enumerate(raw_samples, start=1):
            if not isinstance(raw, dict):
                raise RuntimeError(f"Depth sample {index} must be an object")
            sample = dict(raw)
            track = _resolve_track(sample, by_id, by_number, index)
            try:
                frame_index = int(sample.get("frame_index"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Depth sample {index} requires an integer frame_index") from exc
            if frame_index < 0 or frame_index >= video.frame_count:
                raise RuntimeError(f"Depth sample {index} frame_index falls outside the video")
            depth = _finite_positive(sample.get("depth"), f"depth_samples[{index}].depth")

            raw_center_x = sample.get("center_x_px")
            raw_center_y = sample.get("center_y_px")
            observation_timestamp: float | None = None
            if raw_center_x is None or raw_center_y is None:
                center_x, center_y, observation_timestamp = _observation_center_at_frame(
                    track,
                    video,
                    frame_index,
                )
            else:
                center_x = _finite(raw_center_x, f"depth_samples[{index}].center_x_px")
                center_y = _finite(raw_center_y, f"depth_samples[{index}].center_y_px")
            if not 0 <= center_x <= video.width_px or not 0 <= center_y <= video.height_px:
                raise RuntimeError(f"Depth sample {index} center falls outside the video frame")

            raw_timestamp = sample.get("timestamp_seconds")
            timestamp = (
                _finite(raw_timestamp, f"depth_samples[{index}].timestamp_seconds")
                if raw_timestamp is not None
                else (
                    float(observation_timestamp)
                    if observation_timestamp is not None
                    else frame_index / video.fps
                )
            )
            x, y, z = _back_project(center_x, center_y, depth, intrinsics)
            samples_by_track[track.id].append(
                {
                    "track_id": track.id,
                    "track_number": track.track_number,
                    "frame_index": frame_index,
                    "timestamp_seconds": timestamp,
                    "center_x_px": center_x,
                    "center_y_px": center_y,
                    "x": x,
                    "y": y,
                    "z": z,
                    "depth": depth,
                    "unit": unit,
                }
            )

        track_results: list[dict[str, Any]] = []
        for track_id, track_samples in sorted(
            samples_by_track.items(),
            key=lambda item: by_id[item[0]].track_number,
        ):
            ordered = sorted(
                track_samples,
                key=lambda item: (item["frame_index"], item["timestamp_seconds"]),
            )
            path_length = 0.0
            speeds: list[float] = []
            skipped_gap_count = 0
            for left, right in pairwise(ordered):
                frame_gap = int(right["frame_index"]) - int(left["frame_index"])
                if maximum_frame_gap is not None and frame_gap > maximum_frame_gap:
                    skipped_gap_count += 1
                    continue
                elapsed = float(right["timestamp_seconds"]) - float(left["timestamp_seconds"])
                if elapsed <= 0:
                    raise RuntimeError(
                        f"Track {by_id[track_id].track_number} contains non-increasing sample times"
                    )
                distance = math.sqrt(
                    (float(right["x"]) - float(left["x"])) ** 2
                    + (float(right["y"]) - float(left["y"])) ** 2
                    + (float(right["z"]) - float(left["z"])) ** 2
                )
                path_length += distance
                speeds.append(distance / elapsed)
            first = ordered[0]
            last = ordered[-1]
            displacement = math.sqrt(
                (float(last["x"]) - float(first["x"])) ** 2
                + (float(last["y"]) - float(first["y"])) ** 2
                + (float(last["z"]) - float(first["z"])) ** 2
            )
            depths = [float(item["z"]) for item in ordered]
            track = by_id[track_id]
            track_results.append(
                {
                    "track_id": track.id,
                    "track_number": track.track_number,
                    "label_class_id": track.label_class_id,
                    "sample_count": len(ordered),
                    "first_frame": int(first["frame_index"]),
                    "last_frame": int(last["frame_index"]),
                    "path_length_3d": path_length,
                    "displacement_3d": displacement,
                    "mean_speed_3d_per_second": (
                        sum(speeds) / len(speeds) if speeds else None
                    ),
                    "maximum_speed_3d_per_second": max(speeds) if speeds else None,
                    "minimum_depth": min(depths),
                    "maximum_depth": max(depths),
                    "depth_range": max(depths) - min(depths),
                    "skipped_gap_count": skipped_gap_count,
                    "trajectory": ordered,
                    "unit": unit,
                }
            )

        selected_tracks = [by_id[track_id] for track_id in samples_by_track]
        provenance = {
            "schema": "reefvision-video-depth-3d-v1",
            "project_id": run.project_id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "video_revision": video.revision,
            "camera_intrinsics": intrinsics,
            "depth_source_kind": depth_source_kind,
            "metric_depth_required": True,
            "relative_monocular_depth_is_metric": False,
            "unit": unit,
            "depth_sample_count": sum(len(items) for items in samples_by_track.values()),
            "source_track_revisions": [
                {
                    "track_id": track.id,
                    "track_number": track.track_number,
                    "revision": track.revision,
                    "origin_job_id": track.origin_job_id,
                    "source_type": track.source_type,
                }
                for track in sorted(selected_tracks, key=lambda item: item.track_number)
            ],
        }

    return {
        "measurements": (
            "measurements",
            {
                "measurement_mode": "video_depth_3d",
                "video_ids": [video_ids[0]],
                "track_ids": [item["track_id"] for item in track_results],
                "track_count": len(track_results),
                "tracks": track_results,
                "coordinate_system": "pinhole_camera_xyz",
                "physical_unit": unit,
                "provenance": provenance,
            },
        )
    }


def _measurement_with_video_depth_3d(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    mode = str(configuration.get("measurement_mode", "coral_mask")).strip().casefold()
    if mode != "video_depth_3d":
        return _ORIGINAL_MEASUREMENTS(factory, run, configuration, inputs)
    return _workflow_video_depth_3d(factory, run, configuration, inputs)


workflow_science_runtime._workflow_measurements = _measurement_with_video_depth_3d
workflow_runs._measurement_snapshot = _measurement_with_video_depth_3d
