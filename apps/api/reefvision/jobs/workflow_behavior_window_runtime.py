"""Frame/time-windowed scientific behavior analysis for Fusion workflows.

Windowing is applied after the shared video behavior service has produced canonical
trajectories, but every metric affected by the interval is recomputed from the selected
samples. Windowed workflows never persist the broader full-video service analysis as if it
represented the requested interval.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import VideoAsset, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_behavior_runtime, workflow_runs
from reefvision.schemas.videos import VideoAnalyticsRequest

_ORIGINAL_BEHAVIOR_REQUEST = workflow_behavior_runtime._behavior_request
_ORIGINAL_BEHAVIOR_SNAPSHOT = workflow_behavior_runtime._configurable_behavior_snapshot
_WINDOW_KEYS = (
    "start_frame",
    "end_frame",
    "start_time_seconds",
    "end_time_seconds",
)


def _has_window(configuration: dict[str, Any]) -> bool:
    return any(configuration.get(key) is not None for key in _WINDOW_KEYS)


def _analysis_window(configuration: dict[str, Any]) -> dict[str, int | float | None]:
    def optional_int(key: str) -> int | None:
        raw = configuration.get(key)
        if raw is None:
            return None
        if isinstance(raw, bool):
            raise RuntimeError(f"behavior_analysis {key} must be an integer")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"behavior_analysis {key} must be an integer") from exc
        if value < 0:
            raise RuntimeError(f"behavior_analysis {key} cannot be negative")
        return value

    def optional_float(key: str) -> float | None:
        raw = configuration.get(key)
        if raw is None:
            return None
        if isinstance(raw, bool):
            raise RuntimeError(f"behavior_analysis {key} must be numeric")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"behavior_analysis {key} must be numeric") from exc
        if not math.isfinite(value) or value < 0:
            raise RuntimeError(f"behavior_analysis {key} must be finite and non-negative")
        return value

    start_frame = optional_int("start_frame")
    end_frame = optional_int("end_frame")
    start_time = optional_float("start_time_seconds")
    end_time = optional_float("end_time_seconds")
    if start_frame is not None and end_frame is not None and start_frame > end_frame:
        raise RuntimeError("behavior_analysis start_frame cannot exceed end_frame")
    if start_time is not None and end_time is not None and start_time > end_time:
        raise RuntimeError(
            "behavior_analysis start_time_seconds cannot exceed end_time_seconds"
        )
    return {
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_time_seconds": start_time,
        "end_time_seconds": end_time,
    }


def _validate_window_for_video(
    window: dict[str, int | float | None],
    video: VideoAsset,
) -> None:
    start_frame = window["start_frame"]
    end_frame = window["end_frame"]
    start_time = window["start_time_seconds"]
    end_time = window["end_time_seconds"]
    if isinstance(start_frame, int) and start_frame >= video.frame_count:
        raise RuntimeError("behavior_analysis start_frame falls outside the video")
    if isinstance(end_frame, int) and end_frame >= video.frame_count:
        raise RuntimeError("behavior_analysis end_frame falls outside the video")
    tolerance = 1.0 / video.fps
    if isinstance(start_time, float) and start_time > video.duration_seconds + tolerance:
        raise RuntimeError("behavior_analysis start_time_seconds falls outside the video")
    if isinstance(end_time, float) and end_time > video.duration_seconds + tolerance:
        raise RuntimeError("behavior_analysis end_time_seconds falls outside the video")


def _sample_in_window(
    sample: dict[str, Any],
    window: dict[str, int | float | None],
) -> bool:
    frame_index = int(sample["frame_index"])
    timestamp = float(sample["timestamp_seconds"])
    start_frame = window["start_frame"]
    end_frame = window["end_frame"]
    start_time = window["start_time_seconds"]
    end_time = window["end_time_seconds"]
    return not (
        (isinstance(start_frame, int) and frame_index < start_frame)
        or (isinstance(end_frame, int) and frame_index > end_frame)
        or (isinstance(start_time, float) and timestamp < start_time)
        or (isinstance(end_time, float) and timestamp > end_time)
    )


def _inside_zone(center: tuple[float, float], zone: dict[str, Any]) -> bool:
    return (
        float(zone["x_min"]) <= center[0] <= float(zone["x_max"])
        and float(zone["y_min"]) <= center[1] <= float(zone["y_max"])
    )


def _window_track(
    track: dict[str, Any],
    *,
    video: VideoAsset,
    window: dict[str, int | float | None],
    distance_per_pixel: float | None,
    physical_unit: str | None,
    activity_threshold: float,
    zones: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    raw_trajectory = track.get("trajectory", [])
    samples = [
        dict(item)
        for item in raw_trajectory
        if isinstance(item, dict) and _sample_in_window(item, window)
    ]
    samples.sort(key=lambda item: (int(item["frame_index"]), float(item["timestamp_seconds"])))
    if not samples:
        return None, []

    centers = [
        (float(item["center_x_pixels"]), float(item["center_y_pixels"]))
        for item in samples
    ]
    times = [float(item["timestamp_seconds"]) for item in samples]
    distances: list[float | None] = [None] * len(samples)
    speeds: list[float | None] = [None] * len(samples)
    elapsed_intervals: list[float | None] = [None] * len(samples)
    vectors: list[tuple[float, float] | None] = [None] * len(samples)
    for index in range(1, len(samples)):
        elapsed = times[index] - times[index - 1]
        if elapsed <= 0:
            continue
        dx = centers[index][0] - centers[index - 1][0]
        dy = centers[index][1] - centers[index - 1][1]
        distance = math.hypot(dx, dy)
        distances[index] = distance
        speeds[index] = distance / elapsed
        elapsed_intervals[index] = elapsed
        vectors[index] = (dx, dy)

    accelerations: list[float | None] = [None] * len(samples)
    turning_angles: list[float | None] = [None] * len(samples)
    angular_velocities: list[float | None] = [None] * len(samples)
    for index in range(2, len(samples)):
        current_speed = speeds[index]
        previous_speed = speeds[index - 1]
        elapsed = elapsed_intervals[index]
        if current_speed is not None and previous_speed is not None and elapsed:
            accelerations[index] = abs(current_speed - previous_speed) / elapsed
        previous_vector = vectors[index - 1]
        current_vector = vectors[index]
        if previous_vector is None or current_vector is None:
            continue
        previous_length = math.hypot(*previous_vector)
        current_length = math.hypot(*current_vector)
        if previous_length == 0 or current_length == 0:
            continue
        dot = previous_vector[0] * current_vector[0] + previous_vector[1] * current_vector[1]
        cross = previous_vector[0] * current_vector[1] - previous_vector[1] * current_vector[0]
        angle = math.degrees(math.atan2(abs(cross), dot))
        turning_angles[index] = angle
        if elapsed:
            angular_velocities[index] = angle / elapsed

    zone_seconds = {str(zone["name"]): 0.0 for zone in zones}
    zone_states = {str(zone["name"]): False for zone in zones}
    zone_events: list[dict[str, Any]] = []
    wall_distances: list[float] = []
    for index, (sample, center) in enumerate(zip(samples, centers, strict=True)):
        wall_distances.append(
            min(
                center[0],
                max(0.0, video.width_px - center[0]),
                center[1],
                max(0.0, video.height_px - center[1]),
            )
        )
        occupancy_elapsed = elapsed_intervals[index]
        for zone in zones:
            name = str(zone["name"])
            inside = _inside_zone(center, zone)
            was_inside = zone_states[name]
            if inside and (index == 0 or not was_inside):
                zone_events.append(
                    {
                        "track_id": str(track["track_id"]),
                        "zone_name": name,
                        "event_type": "entry",
                        "frame_index": int(sample["frame_index"]),
                        "timestamp_seconds": float(sample["timestamp_seconds"]),
                    }
                )
            elif was_inside and not inside:
                zone_events.append(
                    {
                        "track_id": str(track["track_id"]),
                        "zone_name": name,
                        "event_type": "exit",
                        "frame_index": int(sample["frame_index"]),
                        "timestamp_seconds": float(sample["timestamp_seconds"]),
                    }
                )
            if occupancy_elapsed is not None and was_inside:
                zone_seconds[name] += occupancy_elapsed
            zone_states[name] = inside

    for index, sample in enumerate(samples):
        sample["distance_from_previous_pixels"] = distances[index]
        sample["distance_from_previous_physical"] = (
            distances[index] * distance_per_pixel
            if distances[index] is not None and distance_per_pixel is not None
            else None
        )
        sample["speed_pixels_per_second"] = speeds[index]
        sample["speed_physical_per_second"] = (
            speeds[index] * distance_per_pixel
            if speeds[index] is not None and distance_per_pixel is not None
            else None
        )
        sample["acceleration_pixels_per_second_squared"] = accelerations[index]
        sample["turning_angle_degrees"] = turning_angles[index]
        sample["angular_velocity_degrees_per_second"] = angular_velocities[index]
        sample["center_x_physical"] = (
            centers[index][0] * distance_per_pixel if distance_per_pixel is not None else None
        )
        sample["center_y_physical"] = (
            centers[index][1] * distance_per_pixel if distance_per_pixel is not None else None
        )

    valid_distances = [value for value in distances if value is not None]
    valid_speeds = [value for value in speeds if value is not None]
    valid_accelerations = [value for value in accelerations if value is not None]
    valid_turning = [value for value in turning_angles if value is not None]
    valid_angular = [value for value in angular_velocities if value is not None]
    valid_elapsed = [value for value in elapsed_intervals if value is not None]
    distance_pixels = sum(valid_distances)
    net_displacement = math.hypot(
        centers[-1][0] - centers[0][0],
        centers[-1][1] - centers[0][1],
    )
    measured_time = sum(valid_elapsed)
    mean_speed = distance_pixels / measured_time if measured_time > 0 else 0.0
    active_time = sum(
        float(elapsed_intervals[index] or 0.0)
        for index, speed in enumerate(speeds)
        if speed is not None and speed >= activity_threshold
    )
    mean_acceleration = mean(valid_accelerations) if valid_accelerations else 0.0
    maximum_acceleration = max(valid_accelerations, default=0.0)
    persisted_count = sum(not bool(item.get("interpolated", False)) for item in samples)

    result = dict(track)
    result.update(
        {
            "first_frame": int(samples[0]["frame_index"]),
            "last_frame": int(samples[-1]["frame_index"]),
            "observed_frame_count": len(samples),
            "persisted_observation_count": persisted_count,
            "duration_seconds": max(0.0, times[-1] - times[0]),
            "distance_pixels": distance_pixels,
            "total_path_length_pixels": distance_pixels,
            "net_displacement_pixels": net_displacement,
            "path_tortuosity": (
                distance_pixels / net_displacement if net_displacement > 0 else None
            ),
            "mean_speed_pixels_per_second": mean_speed,
            "maximum_speed_pixels_per_second": max(valid_speeds, default=0.0),
            "mean_acceleration_pixels_per_second_squared": mean_acceleration,
            "maximum_acceleration_pixels_per_second_squared": maximum_acceleration,
            "mean_turning_angle_degrees": mean(valid_turning) if valid_turning else None,
            "cumulative_turning_angle_degrees": sum(valid_turning),
            "mean_angular_velocity_degrees_per_second": (
                mean(valid_angular) if valid_angular else None
            ),
            "mean_distance_to_wall_pixels": mean(wall_distances),
            "active_time_seconds": active_time,
            "inactive_time_seconds": max(0.0, measured_time - active_time),
            "distance_physical": (
                distance_pixels * distance_per_pixel if distance_per_pixel is not None else None
            ),
            "net_displacement_physical": (
                net_displacement * distance_per_pixel
                if distance_per_pixel is not None
                else None
            ),
            "mean_speed_physical_per_second": (
                mean_speed * distance_per_pixel if distance_per_pixel is not None else None
            ),
            "maximum_speed_physical_per_second": (
                max(valid_speeds, default=0.0) * distance_per_pixel
                if distance_per_pixel is not None
                else None
            ),
            "mean_acceleration_physical_per_second_squared": (
                mean_acceleration * distance_per_pixel
                if distance_per_pixel is not None
                else None
            ),
            "maximum_acceleration_physical_per_second_squared": (
                maximum_acceleration * distance_per_pixel
                if distance_per_pixel is not None
                else None
            ),
            "mean_distance_to_wall_physical": (
                mean(wall_distances) * distance_per_pixel
                if distance_per_pixel is not None
                else None
            ),
            "physical_unit": physical_unit,
            "zone_time_seconds": zone_seconds,
            "trajectory": samples,
        }
    )
    return result, zone_events


def _window_aware_behavior_request(
    configuration: dict[str, Any],
    *,
    persist_result: bool,
) -> VideoAnalyticsRequest:
    if _has_window(configuration):
        persist_result = False
    return _ORIGINAL_BEHAVIOR_REQUEST(configuration, persist_result=persist_result)


def _windowed_behavior_snapshot(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    configuration = workflow_behavior_runtime._current_node_configuration(factory, run)
    if not _has_window(configuration):
        return _ORIGINAL_BEHAVIOR_SNAPSHOT(factory, run, inputs)

    window = _analysis_window(configuration)
    outputs = _ORIGINAL_BEHAVIOR_SNAPSHOT(factory, run, inputs)
    output = outputs.get("measurements")
    if output is None:
        raise RuntimeError("Behavior workflow did not produce a measurements artifact")
    artifact_type, payload = output
    payload = dict(payload)
    analyses = [dict(item) for item in payload.get("analyses", []) if isinstance(item, dict)]

    with factory() as session:
        for analysis in analyses:
            video_id = str(analysis.get("video_id", ""))
            video = session.get(VideoAsset, video_id)
            if video is None or video.project_id != run.project_id:
                raise RuntimeError("Windowed behavior video is missing from the workflow project")
            _validate_window_for_video(window, video)
            raw_scale = analysis.get("distance_per_pixel")
            distance_per_pixel = float(raw_scale) if raw_scale is not None else None
            physical_unit = (
                str(analysis["physical_unit"])
                if analysis.get("physical_unit") is not None
                else None
            )
            workflow_configuration = analysis.get("workflow_configuration", {})
            if not isinstance(workflow_configuration, dict):
                workflow_configuration = {}
            activity_threshold = float(
                workflow_configuration.get(
                    "activity_speed_threshold_pixels_per_second",
                    configuration.get("activity_speed_threshold_pixels_per_second", 1.0),
                )
            )
            service_configuration = analysis.get("configuration", {})
            resolved_zones = (
                service_configuration.get("resolved_zones", [])
                if isinstance(service_configuration, dict)
                else []
            )
            zones = [dict(zone) for zone in resolved_zones if isinstance(zone, dict)]

            windowed_tracks: list[dict[str, Any]] = []
            zone_events: list[dict[str, Any]] = []
            excluded_track_ids: list[str] = []
            for raw_track in analysis.get("tracks", []):
                if not isinstance(raw_track, dict):
                    continue
                windowed, events = _window_track(
                    dict(raw_track),
                    video=video,
                    window=window,
                    distance_per_pixel=distance_per_pixel,
                    physical_unit=physical_unit,
                    activity_threshold=activity_threshold,
                    zones=zones,
                )
                if windowed is None:
                    excluded_track_ids.append(str(raw_track.get("track_id", "")))
                    continue
                windowed_tracks.append(windowed)
                zone_events.extend(events)

            analysis["tracks"] = windowed_tracks
            analysis["zone_events"] = sorted(
                zone_events,
                key=lambda item: (
                    float(item["timestamp_seconds"]),
                    str(item["track_id"]),
                    str(item["zone_name"]).casefold(),
                    str(item["event_type"]),
                ),
            )
            analysis["analysis_id"] = None
            analysis["_source_dimensions"] = {
                "width_px": video.width_px,
                "height_px": video.height_px,
            }
            selected_ids = {str(track["track_id"]) for track in windowed_tracks}
            analysis = workflow_behavior_runtime._filtered_aggregates(
                analysis,
                selected_ids,
                _window_aware_behavior_request(configuration, persist_result=False),
            )
            source_revisions: list[dict[str, Any]] = []
            observed_by_track = {
                str(track["track_id"]): int(track["persisted_observation_count"])
                for track in windowed_tracks
            }
            for raw_revision in analysis.get("source_track_revisions", []):
                if not isinstance(raw_revision, dict):
                    continue
                revision = dict(raw_revision)
                revision["window_observation_count"] = observed_by_track.get(
                    str(revision.get("track_id")),
                    0,
                )
                source_revisions.append(revision)
            analysis["source_track_revisions"] = source_revisions
            workflow_configuration = dict(analysis.get("workflow_configuration", {}))
            workflow_configuration["analysis_window"] = dict(window)
            workflow_configuration["persisted_service_result"] = False
            analysis["workflow_configuration"] = workflow_configuration
            if isinstance(analysis.get("configuration"), dict):
                analysis["configuration"] = {
                    **dict(analysis["configuration"]),
                    "analysis_window": dict(window),
                }
            warnings = list(analysis.get("warnings", []))
            warnings.append(
                "Behavior metrics were recomputed from the selected inclusive frame/time window."
            )
            if excluded_track_ids:
                warnings.append(
                    f"{len(excluded_track_ids)} track(s) had no samples inside the analysis window."
                )
            analysis["warnings"] = warnings

    payload["analyses"] = analyses
    payload["analysis_ids"] = []
    payload["analysis_count"] = len(analyses)
    payload["track_ids"] = list(
        dict.fromkeys(
            str(track["track_id"])
            for analysis in analyses
            for track in analysis.get("tracks", [])
            if isinstance(track, dict) and track.get("track_id") is not None
        )
    )
    payload["measurement_engine"] = "video_behavior_windowed"
    payload["windowed"] = True
    payload["analysis_window"] = dict(window)
    return {"measurements": (artifact_type, payload)}


workflow_behavior_runtime._behavior_request = _window_aware_behavior_request
workflow_runs._behavior_snapshot = _windowed_behavior_snapshot
