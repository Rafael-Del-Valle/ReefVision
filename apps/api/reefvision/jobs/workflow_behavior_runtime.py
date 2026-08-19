"""Configurable scientific fish-behavior analysis for Fusion workflows.

The base video service remains the single implementation of per-track kinematics and zone
logic. This workflow bridge exposes its request controls, constrains results to the tracks
actually connected to the node, and recomputes school/heatmap aggregates for that selected
track set so subset workflows remain scientifically valid.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import get_settings
from reefvision.db.models import WorkflowArtifact, WorkflowRevision, WorkflowRun
from reefvision.jobs import workflow_runs
from reefvision.schemas.videos import VideoAnalyticsRequest
from reefvision.services.video_behavior import VideoBehaviorAnalysisService


def _current_node_configuration(
    factory: sessionmaker[Session],
    run: WorkflowRun,
) -> dict[str, Any]:
    node_id = run.current_node_id
    if not node_id:
        return {}
    with factory() as session:
        revision = session.get(WorkflowRevision, run.workflow_revision_id)
        if revision is None:
            raise RuntimeError("Workflow revision disappeared during behavior analysis")
        workflow = dict(revision.workflow_json or {})
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return {}
    for raw_node in nodes:
        if not isinstance(raw_node, dict) or raw_node.get("id") != node_id:
            continue
        configuration = raw_node.get("configuration")
        return dict(configuration) if isinstance(configuration, dict) else {}
    return {}


def _behavior_request(configuration: dict[str, Any], *, persist_result: bool) -> VideoAnalyticsRequest:
    payload: dict[str, Any] = {
        "include_saved_zones": bool(configuration.get("include_saved_zones", True)),
        "heatmap_bins_x": int(configuration.get("heatmap_bins_x", 20)),
        "heatmap_bins_y": int(configuration.get("heatmap_bins_y", 20)),
        "activity_speed_threshold_pixels_per_second": float(
            configuration.get("activity_speed_threshold_pixels_per_second", 1.0)
        ),
        "sampling": str(configuration.get("sampling", "interpolated")),
        "persist_result": persist_result,
    }
    zones = configuration.get("zones")
    if zones is not None:
        payload["zones"] = zones
    try:
        return VideoAnalyticsRequest.model_validate(payload)
    except Exception as exc:
        raise RuntimeError(f"Invalid behavior-analysis configuration: {exc}") from exc


def _selected_track_ids(
    payloads: list[dict[str, Any]],
    configuration: dict[str, Any],
) -> tuple[set[str] | None, bool]:
    """Resolve the exact track scope represented by the connected workflow artifact.

    None means the upstream artifact does not declare track identity and the service may
    analyze all active tracks for the referenced video. An empty set means the upstream
    tracker explicitly produced zero tracks and must remain an empty scientific result.
    """

    scope_declared = any("track_ids" in payload for payload in payloads)
    connected = {
        str(track_id)
        for payload in payloads
        for track_id in payload.get("track_ids", [])
        if isinstance(payload.get("track_ids"), list)
    }
    configured_raw = configuration.get("track_ids")
    if configured_raw is None:
        return (connected if scope_declared else None), scope_declared
    if not isinstance(configured_raw, list):
        raise RuntimeError("behavior_analysis track_ids must be a list")
    configured = {str(track_id) for track_id in configured_raw}
    if scope_declared and not configured.issubset(connected):
        raise RuntimeError(
            "behavior_analysis track_ids must be a subset of the connected tracks artifact"
        )
    return configured, True


def _filtered_aggregates(
    analysis: dict[str, Any],
    selected_ids: set[str],
    request: VideoAnalyticsRequest,
) -> dict[str, Any]:
    tracks = [
        track
        for track in analysis.get("tracks", [])
        if isinstance(track, dict) and str(track.get("track_id")) in selected_ids
    ]
    found_ids = {str(track["track_id"]) for track in tracks}
    missing = sorted(selected_ids - found_ids)
    if missing:
        raise RuntimeError(
            "One or more connected behavior-analysis tracks are unavailable: " + ", ".join(missing)
        )

    centers_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
    timestamps_by_frame: dict[int, list[float]] = defaultdict(list)
    directions_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
    heatmap_counts: Counter[tuple[int, int]] = Counter()
    heatmap_seconds: defaultdict[tuple[int, int], float] = defaultdict(float)

    video_width = 0.0
    video_height = 0.0
    # The response does not duplicate source dimensions, but normalized heatmap placement
    # can be recovered from the configured bin indices only when dimensions are known.
    # Workflow provenance therefore accepts optional dimensions injected by the caller.
    source_dimensions = analysis.get("_source_dimensions")
    if isinstance(source_dimensions, dict):
        video_width = float(source_dimensions.get("width_px", 0.0))
        video_height = float(source_dimensions.get("height_px", 0.0))
    if video_width <= 0 or video_height <= 0:
        raise RuntimeError("Behavior workflow requires source video dimensions")

    for track in tracks:
        raw_trajectory = track.get("trajectory", [])
        trajectory = [item for item in raw_trajectory if isinstance(item, dict)]
        trajectory.sort(key=lambda item: (int(item["frame_index"]), float(item["timestamp_seconds"])))
        previous: dict[str, Any] | None = None
        for sample in trajectory:
            frame_index = int(sample["frame_index"])
            timestamp = float(sample["timestamp_seconds"])
            center = (
                float(sample["center_x_pixels"]),
                float(sample["center_y_pixels"]),
            )
            centers_by_frame[frame_index].append(center)
            timestamps_by_frame[frame_index].append(timestamp)
            column = min(
                request.heatmap_bins_x - 1,
                max(0, int(center[0] / video_width * request.heatmap_bins_x)),
            )
            row = min(
                request.heatmap_bins_y - 1,
                max(0, int(center[1] / video_height * request.heatmap_bins_y)),
            )
            heatmap_counts[(column, row)] += 1
            if previous is not None:
                elapsed = timestamp - float(previous["timestamp_seconds"])
                if elapsed > 0:
                    heatmap_seconds[(column, row)] += elapsed
                dx = center[0] - float(previous["center_x_pixels"])
                dy = center[1] - float(previous["center_y_pixels"])
                distance = math.hypot(dx, dy)
                if distance > 0:
                    directions_by_frame[frame_index].append((dx / distance, dy / distance))
            previous = sample

    scale_raw = analysis.get("distance_per_pixel")
    distance_per_pixel = float(scale_raw) if scale_raw is not None else None
    school_by_frame: list[dict[str, Any]] = []
    fps = float(analysis.get("fps", 1.0))
    for frame_index, centers in sorted(centers_by_frame.items()):
        frame_timestamps = timestamps_by_frame[frame_index]
        centroid_x = mean(point[0] for point in centers)
        centroid_y = mean(point[1] for point in centers)
        nearest: list[float] = []
        pairwise_distances: list[float] = []
        if len(centers) >= 2:
            for first_index, first in enumerate(centers):
                distances_to_others = [
                    math.hypot(first[0] - second[0], first[1] - second[1])
                    for second_index, second in enumerate(centers)
                    if second_index != first_index
                ]
                nearest.append(min(distances_to_others))
                for second in centers[first_index + 1 :]:
                    pairwise_distances.append(
                        math.hypot(first[0] - second[0], first[1] - second[1])
                    )
            spread = math.sqrt(
                mean(
                    (point[0] - centroid_x) ** 2 + (point[1] - centroid_y) ** 2
                    for point in centers
                )
            )
            mean_nearest = mean(nearest)
            mean_pairwise = mean(pairwise_distances)
        else:
            spread = None
            mean_nearest = None
            mean_pairwise = None
        directions = directions_by_frame.get(frame_index, [])
        polarization = (
            math.hypot(
                sum(direction[0] for direction in directions),
                sum(direction[1] for direction in directions),
            )
            / len(directions)
            if len(directions) >= 2
            else None
        )

        def scaled(value: float | None) -> float | None:
            return value * distance_per_pixel if value is not None and distance_per_pixel else None

        school_by_frame.append(
            {
                "frame_index": frame_index,
                "timestamp_seconds": mean(frame_timestamps) if frame_timestamps else frame_index / fps,
                "active_track_count": len(centers),
                "school_centroid_x_pixels": centroid_x,
                "school_centroid_y_pixels": centroid_y,
                "mean_nearest_neighbor_pixels": mean_nearest,
                "mean_pairwise_distance_pixels": mean_pairwise,
                "school_spread_pixels": spread,
                "polarization": polarization,
                "mean_nearest_neighbor_physical": scaled(mean_nearest),
                "mean_pairwise_distance_physical": scaled(mean_pairwise),
                "school_spread_physical": scaled(spread),
                "school_centroid_x_physical": scaled(centroid_x),
                "school_centroid_y_physical": scaled(centroid_y),
            }
        )

    analysis["tracks"] = tracks
    analysis["school_by_frame"] = school_by_frame
    analysis["heatmap"] = [
        {
            "column": column,
            "row": row,
            "observation_count": count,
            "occupancy_seconds": heatmap_seconds[(column, row)],
        }
        for (column, row), count in sorted(heatmap_counts.items())
    ]
    analysis["zone_events"] = [
        event
        for event in analysis.get("zone_events", [])
        if isinstance(event, dict) and str(event.get("track_id")) in selected_ids
    ]
    analysis["source_track_revisions"] = [
        item
        for item in analysis.get("source_track_revisions", [])
        if isinstance(item, dict) and str(item.get("track_id")) in selected_ids
    ]
    analysis.pop("_source_dimensions", None)
    return analysis


def _configurable_behavior_snapshot(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    configuration = _current_node_configuration(factory, run)
    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    video_ids = workflow_runs._list_values(payloads, "video_ids")
    selected_ids, track_scope_declared = _selected_track_ids(payloads, configuration)
    persist_requested = bool(configuration.get("persist_result", True))
    # A persisted service analysis must never claim the statistics of a broader track set
    # when a workflow requested a subset. Subset analyses remain immutable workflow
    # artifacts and can be exported with exact selection provenance.
    request = _behavior_request(
        configuration,
        persist_result=persist_requested and not track_scope_declared,
    )
    settings = get_settings()
    analyses: list[dict[str, Any]] = []
    with factory() as session:
        service = VideoBehaviorAnalysisService(session, settings)
        from reefvision.db.models import VideoAsset

        for video_id in video_ids:
            video = session.get(VideoAsset, video_id)
            if video is None or video.project_id != run.project_id:
                raise RuntimeError("Behavior workflow video is missing from the workflow project")
            response = service.analytics(video_id, request)
            analysis = response.model_dump(mode="json")
            analysis["_source_dimensions"] = {
                "width_px": video.width_px,
                "height_px": video.height_px,
            }
            if selected_ids is not None:
                analysis = _filtered_aggregates(analysis, selected_ids, request)
                analysis["analysis_id"] = None
                analysis.setdefault("warnings", []).append(
                    "Workflow behavior statistics were restricted to the connected track set; "
                    "the subset result is stored in workflow provenance rather than as a broad "
                    "persisted video-analysis run."
                )
            else:
                analysis.pop("_source_dimensions", None)
            analysis["workflow_configuration"] = {
                "sampling": request.sampling,
                "include_saved_zones": request.include_saved_zones,
                "zones": [zone.model_dump(mode="json") for zone in request.zones],
                "heatmap_bins_x": request.heatmap_bins_x,
                "heatmap_bins_y": request.heatmap_bins_y,
                "activity_speed_threshold_pixels_per_second": (
                    request.activity_speed_threshold_pixels_per_second
                ),
                "requested_track_ids": sorted(selected_ids) if selected_ids is not None else None,
                "persist_result_requested": persist_requested,
                "persisted_service_result": request.persist_result,
            }
            analyses.append(analysis)

    track_ids = list(
        dict.fromkeys(
            str(track["track_id"])
            for analysis in analyses
            for track in analysis.get("tracks", [])
            if isinstance(track, dict) and track.get("track_id") is not None
        )
    )
    analysis_ids = [
        str(analysis["analysis_id"])
        for analysis in analyses
        if analysis.get("analysis_id") is not None
    ]
    return {
        "measurements": (
            "measurements",
            {
                "video_ids": video_ids,
                "track_ids": track_ids,
                "analysis_ids": analysis_ids,
                "analysis_count": len(analyses),
                "analyses": analyses,
                "measurement_engine": "video_behavior",
                "calibration_aware": True,
                "track_scope": (
                    "connected_tracks" if selected_ids is not None else "all_active_video_tracks"
                ),
            },
        )
    }


workflow_runs._behavior_snapshot = _configurable_behavior_snapshot
