"""Workflow adapter for automatic Metric Video Depth Anything Scientific 3D."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.jobs.video_metric_depth import process_video_metric_depth_job
from reefvision.services import workflow_runtime_adapters as runtime_adapters

NODE_TYPE = "video_metric_depth_3d"
OUTPUT_DATA_TYPE = "video_3d_trajectories"


def _single_payload(
    inputs: dict[str, list[WorkflowArtifact]],
    port_id: str,
) -> dict[str, Any]:
    artifacts = inputs.get(port_id, [])
    if len(artifacts) != 1:
        raise ValidationError(f"Workflow input {port_id!r} requires exactly one artifact")
    return dict(artifacts[0].payload_json or {})


def execute_video_metric_depth_3d_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    video_payload = _single_payload(inputs, "video")
    tracks_payload = _single_payload(inputs, "tracks")
    video_id = video_payload.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        raise ValidationError("Automatic Scientific 3D requires a video_reference input")
    if video_payload.get("project_id") not in {None, project_id}:
        raise ValidationError("Automatic Scientific 3D received a video from another project")
    if tracks_payload.get("project_id") not in {None, project_id}:
        raise ValidationError("Automatic Scientific 3D received tracks from another project")
    if tracks_payload.get("video_id") not in {None, video_id}:
        raise ValidationError("Automatic Scientific 3D tracks belong to another video")

    track_ids = [
        str(value)
        for value in tracks_payload.get("track_ids", [])
        if isinstance(value, str) and value
    ]
    if not track_ids:
        raw_tracks = tracks_payload.get("tracks", [])
        if isinstance(raw_tracks, list):
            track_ids = [
                str(item.get("track_id") or item.get("id"))
                for item in raw_tracks
                if isinstance(item, dict) and (item.get("track_id") or item.get("id"))
            ]
    track_ids = list(dict.fromkeys(track_ids))
    if not track_ids:
        raise ValidationError("Automatic Scientific 3D requires at least one incoming track")

    job = Job(
        project_id=project_id,
        job_type="video_metric_depth_3d",
        status="queued",
        progress_current=0,
        progress_total=1,
        request_json={
            "video_id": video_id,
            "track_ids": track_ids,
            "device": str(parameters.get("device", "auto")),
            "input_size": int(parameters.get("input_size", 518)),
            "max_res": int(parameters.get("max_res", 1280)),
            "core_fraction": float(parameters.get("core_fraction", 0.6)),
            "minimum_valid_fraction": float(parameters.get("minimum_valid_fraction", 0.25)),
            "maximum_frame_gap": parameters.get("maximum_frame_gap"),
            "allow_model_download": bool(parameters.get("allow_model_download", False)),
            "allow_resolution_fallback": bool(parameters.get("allow_resolution_fallback", True)),
            "created_by_workflow": True,
        },
        result_json={
            "stage": "queued",
            "created_by_workflow": True,
            "depth_tier": "model_estimated_metric",
            "physical_measurement_claim_allowed": False,
        },
    )
    session.add(job)
    session.commit()
    child_job_id = job.id

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    process_video_metric_depth_job(settings, factory, child_job_id)
    session.expire_all()
    completed = session.get(Job, child_job_id)
    if completed is None or completed.status != "succeeded":
        detail = completed.error_message if completed is not None else "job disappeared"
        raise ValidationError(f"Automatic Scientific 3D workflow child job failed: {detail}")

    output = dict(completed.result_json or {})
    output["workflow_provenance"] = {
        "schema_version": "video-metric-depth-3d-workflow-provenance-0001",
        "project_id": project_id,
        "video_id": video_id,
        "source_track_ids": track_ids,
        "child_job_id": child_job_id,
        "depth_tier": output.get("depth_tier", "model_estimated_metric"),
        "physical_measurement_claim_allowed": bool(
            output.get("physical_measurement_claim_allowed", False)
        ),
        "automatic_model_download_allowed": bool(parameters.get("allow_model_download", False)),
    }
    return [
        {
            "port_id": "trajectories",
            "data_type": OUTPUT_DATA_TYPE,
            "payload_json": output,
        }
    ]


def register_video_metric_depth_3d_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    runtime_adapters._ADAPTERS[NODE_TYPE] = execute_video_metric_depth_3d_adapter
