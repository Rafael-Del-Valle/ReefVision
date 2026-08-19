"""CoralVision 1.0 workflow adapter for calibrated 3D video trajectories."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.video_science import VideoDepthTrackAnalyticsRequest
from reefvision.services import workflow_runtime_adapters as runtime_adapters
from reefvision.services.video_science import VideoScienceService

NODE_TYPE = "video_depth_3d_analytics"
OUTPUT_DATA_TYPE = "video_3d_trajectories"


def _single_payload(
    inputs: dict[str, list[WorkflowArtifact]],
    port_id: str,
) -> dict[str, Any]:
    artifacts = inputs.get(port_id, [])
    if len(artifacts) != 1:
        raise ValidationError(f"Workflow input {port_id!r} requires exactly one artifact")
    return dict(artifacts[0].payload_json or {})


def _track_identity_maps(
    payload: dict[str, Any],
) -> tuple[set[str], dict[int, str]]:
    raw_tracks = payload.get("tracks", [])
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise ValidationError("3D trajectory analysis requires at least one incoming video track")
    track_ids: set[str] = set()
    by_number: dict[int, str] = {}
    for raw in raw_tracks:
        if not isinstance(raw, dict):
            continue
        track_id = raw.get("track_id") or raw.get("id")
        track_number = raw.get("track_number")
        if isinstance(track_id, str) and track_id:
            track_ids.add(track_id)
            if isinstance(track_number, int):
                by_number[track_number] = track_id
    if not track_ids:
        raise ValidationError("Incoming video-track artifact contains no persisted track IDs")
    return track_ids, by_number


def _resolve_depth_samples(
    parameters: dict[str, Any],
    allowed_track_ids: set[str],
    track_ids_by_number: dict[int, str],
) -> list[dict[str, Any]]:
    raw_samples = parameters.get("depth_samples")
    if not isinstance(raw_samples, list) or len(raw_samples) < 2:
        raise ValidationError(
            "3D trajectory analysis requires depth_samples with at least two metric samples"
        )

    resolved: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_samples, start=1):
        if not isinstance(raw, dict):
            raise ValidationError(f"Depth sample {index} must be an object")
        sample = dict(raw)
        track_id = sample.get("track_id")
        track_number = sample.get("track_number")
        if not isinstance(track_id, str) or not track_id:
            if isinstance(track_number, int):
                track_id = track_ids_by_number.get(track_number)
            elif isinstance(track_number, str) and track_number.strip().isdigit():
                track_id = track_ids_by_number.get(int(track_number.strip()))
        if not isinstance(track_id, str) or track_id not in allowed_track_ids:
            raise ValidationError(
                f"Depth sample {index} must reference a track from the incoming "
                "video_tracks artifact"
            )
        sample.pop("track_number", None)
        sample["track_id"] = track_id
        resolved.append(sample)
    return resolved


def execute_video_depth_3d_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    video_payload = _single_payload(inputs, "video")
    tracks_payload = _single_payload(inputs, "tracks")
    video_id = video_payload.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        raise ValidationError("3D trajectory analysis requires a video_reference input")

    track_ids, track_ids_by_number = _track_identity_maps(tracks_payload)
    samples = _resolve_depth_samples(parameters, track_ids, track_ids_by_number)
    unit = parameters.get("unit", "m")
    maximum_frame_gap = parameters.get("maximum_frame_gap")
    request = VideoDepthTrackAnalyticsRequest.model_validate(
        {
            "unit": unit,
            "samples": samples,
            "maximum_frame_gap": maximum_frame_gap,
        }
    )
    result = VideoScienceService(session).depth_track_analytics(video_id, request)
    output = result.model_dump(mode="json")
    output["workflow_provenance"] = {
        "schema_version": "video-depth-workflow-provenance-0001",
        "project_id": project_id,
        "video_id": video_id,
        "source_track_ids": sorted(track_ids),
        "metric_depth_sample_count": len(samples),
        "depth_source_requirement": "calibrated_metric_depth",
        "relative_monocular_depth_is_metric": False,
    }
    return [
        {
            "port_id": "trajectories",
            "data_type": OUTPUT_DATA_TYPE,
            "payload_json": output,
        }
    ]


def register_video_depth_3d_adapter() -> None:
    """Install the 1.0 adapter into the existing M10 runtime table in-place."""

    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    runtime_adapters._ADAPTERS[NODE_TYPE] = execute_video_depth_3d_adapter
