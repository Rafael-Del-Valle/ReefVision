"""Portable remapping for immutable organism-pose link evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from reefvision.schemas.ecology_pose_links import PoseLinkSource
from reefvision.storage.datasets import canonical_json_sha256


def remap_pose_link_source(
    source: dict[str, Any],
    *,
    map_id: Callable[[str, str], str],
    map_digest: Callable[[str, str], str],
) -> tuple[dict[str, Any], str]:
    """Rebind recorded IDs and checksums without reading mutable source rows."""
    validated = PoseLinkSource.model_validate(source)
    payload = validated.model_dump(mode="json")
    payload["video_id"] = map_id("videos", validated.video_id)
    payload["pose_schema_id"] = map_id("pose_landmark_schemas", validated.pose_schema_id)
    for name in ("pose_schema_sha256", "input_manifest_sha256"):
        payload[name] = map_digest(name, payload[name])
    for observation in payload["observations"]:
        observation["id"] = map_id("pose_identity_observations", observation["id"])
        observation["observation_series_id"] = map_id(
            "pose_identity_observation_series", observation["observation_series_id"]
        )
        observation["source_video_track_id"] = map_id(
            "video_tracks", observation["source_video_track_id"]
        )
    for measurement in payload["measurements"]:
        measurement["id"] = map_id("pose_measurement_series", measurement["id"])
        measurement["run_id"] = map_id("pose_measurement_runs", measurement["run_id"])
        for name in ("series_sha256", "result_sha256"):
            measurement[name] = map_digest(name, measurement[name])
    for event in payload["events"]:
        event["id"] = map_id("pose_biological_event_revisions", event["id"])
        event["event_series_id"] = map_id("pose_biological_event_series", event["event_series_id"])
        event["run_id"] = map_id("pose_event_detection_runs", event["run_id"])
        event["measurement_series_id"] = map_id(
            "pose_measurement_series", event["measurement_series_id"]
        )
        event["after_sha256"] = map_digest("after_sha256", event["after_sha256"])
    payload["measurements"].sort(key=lambda row: row["id"])
    payload["events"].sort(key=lambda row: row["id"])
    return payload, canonical_json_sha256(payload)
