"""Workflow adapters over ReefVision's canonical pose science services."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    Project,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.schemas.behavior_dynamics import BehaviorDynamicsRequest
from reefvision.schemas.pose_active_learning import (
    PoseActiveLearningRoundCreateRequest,
)
from reefvision.schemas.pose_tracking import (
    PoseTemporalAssociationBuildRequest,
)
from reefvision.schemas.pose_training_datasets import (
    PoseTrainingDatasetCreateRequest,
    PoseTrainingExportFormat,
)
from reefvision.services import workflow_runtime_adapters as runtime_adapters
from reefvision.services.behavior_dynamics import BehaviorDynamicsService
from reefvision.services.pose_active_learning import PoseActiveLearningService
from reefvision.services.pose_temporal_tracking import (
    PoseTemporalTrackingService,
)
from reefvision.services.pose_training_datasets import (
    PoseTrainingDatasetService,
)
from reefvision.services.pose_training_exports import (
    PoseTrainingExportService,
)
from reefvision.services.workflow_review import (
    WorkflowReviewRequired,
    pose_active_learning_review_status,
    pose_temporal_review_status,
)
from reefvision.storage.projects import resolve_managed_project_path

POSE_WORKFLOW_RUNTIME_NODE_TYPES = {
    "pose_inference",
    "pose_temporal_association",
    "behavior_dynamics",
    "pose_active_learning",
    "pose_review_gate",
    "pose_active_learning_review_gate",
    "pose_training_dataset_freeze",
    "pose_training_export",
}

_EXTERNAL_POSE_EXPORT_FORMATS = {
    "slp",
    "nwb",
    "coco",
    "dlc_csv",
    "ultralytics_pose",
}


def _single_payload(
    inputs: dict[str, list[WorkflowArtifact]],
    port_id: str,
) -> dict[str, Any]:
    artifacts = inputs.get(port_id, [])
    if len(artifacts) != 1:
        raise ValidationError(f"Workflow input requires exactly one artifact: {port_id}")
    return dict(artifacts[0].payload_json or {})


def _track_ids(
    payload: dict[str, Any],
) -> list[str]:
    raw = payload.get("track_ids", [])
    if not isinstance(raw, list):
        raise ValidationError("Pose workflow track_ids must be a list")

    values = [str(value) for value in raw if isinstance(value, str) and value]

    values = list(dict.fromkeys(values))

    if not values:
        raise ValidationError("Pose workflow requires at least one video track")

    return values


def _scoped_tracks(
    session: Session,
    *,
    project_id: str,
    track_ids: list[str],
) -> tuple[list[VideoTrack], VideoAsset]:
    tracks = list(
        session.scalars(
            select(VideoTrack)
            .where(
                VideoTrack.id.in_(track_ids),
                VideoTrack.deleted_at.is_(None),
            )
            .order_by(
                VideoTrack.track_number,
                VideoTrack.id,
            )
        )
    )

    if len(tracks) != len(track_ids):
        raise ValidationError("One or more pose workflow tracks no longer exist")

    video_ids = {track.video_id for track in tracks}

    if len(video_ids) != 1:
        raise ValidationError("One pose workflow artifact must reference exactly one video")

    video_id = next(iter(video_ids))
    video = session.get(VideoAsset, video_id)

    if video is None or video.project_id != project_id:
        raise ValidationError("Pose workflow tracks do not belong to this project")

    return tracks, video


def execute_pose_inference_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    video_payload = _single_payload(
        inputs,
        "video",
    )
    model_payload = _single_payload(
        inputs,
        "model",
    )

    if video_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose Inference received a video from another project")

    if model_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose Inference received a model from another project")

    video_id = str(video_payload.get("video_id") or "")
    model_id = str(model_payload.get("model_id") or "")

    video = session.get(
        VideoAsset,
        video_id,
    )
    model = session.get(
        ModelRegistration,
        model_id,
    )

    if video is None or video.project_id != project_id:
        raise ValidationError("Pose Inference requires a video from this project")

    if model is None or model.project_id != project_id:
        raise ValidationError("Pose Inference requires a model from this project")

    # Pose registrations currently use detector as the broad model
    # purpose while task='pose' distinguishes the scientific operation.
    if model.purpose != "detector" or model.task != "pose":
        raise ValidationError("Pose Inference requires a registered pose model")

    raw_schema = dict(model.metadata_json or {}).get("pose_landmark_schema")

    if not isinstance(raw_schema, dict):
        raise ValidationError("Pose Inference requires a bound ReefVision landmark schema")

    workflow_run_id = parameters.get("__workflow_run_id")
    workflow_node_run_id = parameters.get("__workflow_node_run_id")

    child_job = runtime_adapters._run_child_job(
        session,
        Job(
            project_id=project_id,
            job_type="video_tracking",
            status="queued",
            progress_current=0,
            progress_total=video.frame_count,
            request_json={
                "video_id": video.id,
                "model_id": model.id,
                "tracker": str(
                    parameters.get(
                        "tracker",
                        "bytetrack.yaml",
                    )
                ),
                "confidence": float(
                    parameters.get(
                        "confidence",
                        0.25,
                    )
                ),
                "iou": float(
                    parameters.get(
                        "iou",
                        0.5,
                    )
                ),
                "minimum_track_frames": int(
                    parameters.get(
                        "minimum_track_frames",
                        1,
                    )
                ),
                "device": str(
                    parameters.get(
                        "device",
                        "auto",
                    )
                ),
                "link_detections": True,
                # Critical Phase 10 separation:
                # normal video-pose jobs retain their existing automatic
                # temporal association behavior. Workflow pose inference
                # defers it to pose_temporal_association.
                "build_pose_temporal_associations": False,
                "created_by_workflow": True,
                "workflow_run_id": workflow_run_id,
                "workflow_node_run_id": workflow_node_run_id,
            },
            result_json={
                "stage": "queued",
                "created_by_workflow": True,
            },
        ),
        process_video_tracking_job,
        settings,
    )

    tracks = list(
        session.scalars(
            select(VideoTrack)
            .where(
                VideoTrack.video_id == video.id,
                VideoTrack.source_job_id == child_job.id,
                VideoTrack.deleted_at.is_(None),
            )
            .order_by(
                VideoTrack.track_number,
                VideoTrack.id,
            )
        )
    )

    if not tracks:
        raise ValidationError("Pose Inference produced no retained pose tracks")

    return [
        {
            "port_id": "poses",
            "data_type": "pose_tracks",
            "payload": {
                "schema_version": ("pose-workflow-tracks-0001"),
                "project_id": project_id,
                "video_id": video.id,
                "video_sha256": video.sha256,
                "video_revision": video.revision,
                "source_model_id": model.id,
                "source_model_sha256": model.sha256,
                "provider_name": model.provider_name,
                "provider_version": model.provider_version,
                "tracking_job_id": child_job.id,
                "pose_schema": dict(raw_schema),
                "track_ids": [track.id for track in tracks],
                "count": len(tracks),
                "tracks": [
                    {
                        "track_id": track.id,
                        "track_number": track.track_number,
                        "track_revision": track.revision,
                        "label_class_id": (track.label_class_id),
                        "source_model_id": (track.source_model_id),
                        "source_job_id": (track.source_job_id),
                        "keyframe_count": len(track.keyframes_json or []),
                    }
                    for track in tracks
                ],
            },
        }
    ]


def execute_pose_temporal_association_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings

    pose_payload = _single_payload(
        inputs,
        "poses",
    )

    if pose_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Temporal Pose Association received foreign pose tracks")

    track_ids = _track_ids(pose_payload)

    tracks, video = _scoped_tracks(
        session,
        project_id=project_id,
        track_ids=track_ids,
    )

    request = PoseTemporalAssociationBuildRequest(
        max_gap_frames=int(
            parameters.get(
                "max_gap_frames",
                5,
            )
        ),
        max_normalized_displacement=float(
            parameters.get(
                "max_normalized_displacement",
                0.35,
            )
        ),
        ambiguity_margin=float(
            parameters.get(
                "ambiguity_margin",
                0.05,
            )
        ),
        confirm_after_observations=int(
            parameters.get(
                "confirm_after_observations",
                3,
            )
        ),
        replace_existing=bool(
            parameters.get(
                "replace_existing",
                False,
            )
        ),
    )

    service = PoseTemporalTrackingService(session)

    builds: list[dict[str, Any]] = []

    for track in tracks:
        result = service.build(
            track.id,
            request,
        )

        builds.append(
            {
                **result.model_dump(mode="json"),
                "source_track_revision": (track.revision),
            }
        )

    return [
        {
            "port_id": "tracks",
            "data_type": "pose_temporal_tracks",
            "payload": {
                "schema_version": ("pose-temporal-workflow-0001"),
                "project_id": project_id,
                "video_id": video.id,
                "video_sha256": video.sha256,
                "track_ids": track_ids,
                "count": len(track_ids),
                "association_parameters": (request.model_dump(mode="json")),
                "builds": builds,
            },
        }
    ]


def execute_behavior_dynamics_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings

    reviewed_payload = _single_payload(
        inputs,
        "poses",
    )

    if reviewed_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Behavior Dynamics received reviewed poses from another project")

    track_ids = _track_ids(reviewed_payload)

    _, video = _scoped_tracks(
        session,
        project_id=project_id,
        track_ids=track_ids,
    )

    request = BehaviorDynamicsRequest(
        ethogram_revision_id=str(parameters.get("ethogram_revision_id") or ""),
        start_frame=parameters.get("start_frame"),
        end_frame=parameters.get("end_frame"),
        include_unreviewed=bool(
            parameters.get(
                "include_unreviewed",
                False,
            )
        ),
    )

    service = BehaviorDynamicsService(session)

    analyses = [
        service.analyze(
            track_id,
            request,
        ).model_dump(mode="json")
        for track_id in track_ids
    ]

    return [
        {
            "port_id": "analysis",
            "data_type": "behavior_analysis",
            "payload": {
                "schema_version": ("behavior-workflow-analysis-0001"),
                "project_id": project_id,
                "video_id": video.id,
                "track_ids": track_ids,
                "ethogram_revision_id": (request.ethogram_revision_id),
                "count": len(analyses),
                "analyses": analyses,
            },
        }
    ]


def execute_pose_active_learning_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings

    temporal_payload = _single_payload(
        inputs,
        "tracks",
    )

    if temporal_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose Active Learning received tracks from another project")

    track_ids = _track_ids(temporal_payload)

    tracks, video = _scoped_tracks(
        session,
        project_id=project_id,
        track_ids=track_ids,
    )

    raw_model_ids = parameters.get("model_ids")

    if isinstance(
        raw_model_ids,
        list,
    ):
        model_ids = [
            str(value)
            for value in raw_model_ids
            if isinstance(
                value,
                str,
            )
            and value
        ]
    else:
        model_ids = []

    if not model_ids:
        model_ids = sorted({track.source_model_id for track in tracks if track.source_model_id})

    run_id = str(parameters.get("__workflow_run_id") or "workflow")

    raw_weights = parameters.get("weights")
    weights = (
        dict(raw_weights)
        if isinstance(
            raw_weights,
            dict,
        )
        else {}
    )

    diversity_balance = bool(
        parameters.get(
            "diversity_balance",
            True,
        )
    )

    request = PoseActiveLearningRoundCreateRequest(
        name=str(parameters.get("name") or ("Workflow pose Active Learning " + run_id[:12])),
        video_id=video.id,
        track_ids=track_ids,
        model_ids=model_ids,
        selection_unit=str(
            parameters.get(
                "selection_unit",
                "frame",
            )
        ),
        requested_size=int(
            parameters.get(
                "requested_size",
                20,
            )
        ),
        clip_radius_frames=int(
            parameters.get(
                "clip_radius_frames",
                5,
            )
        ),
        minimum_frame_spacing=int(
            parameters.get(
                "minimum_frame_spacing",
                5,
            )
        ),
        selection_mode=("uncertainty_diverse" if diversity_balance else "uncertainty"),
        diversity_weight=float(
            parameters.get(
                "diversity_weight",
                0.25,
            )
        ),
        weights=weights,
        created_by="workflow",
    )

    service = PoseActiveLearningService(session)

    round_record = service.create_round(
        project_id,
        request,
    )

    candidates = service.list_candidates(round_record.id)

    return [
        {
            "port_id": "round",
            "data_type": "pose_active_learning_round",
            "payload": {
                "schema_version": ("pose-active-learning-workflow-0001"),
                "project_id": project_id,
                "video_id": video.id,
                "round_id": round_record.id,
                "status": round_record.status,
                "selection_sha256": (round_record.selection_sha256),
                "selected_count": (round_record.selected_count),
                "candidate_ids": [candidate.id for candidate in candidates],
                "candidate_count": len(candidates),
                "source_track_ids": track_ids,
                "source_model_ids": model_ids,
            },
        }
    ]


def execute_pose_training_dataset_freeze_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings

    round_payload = _single_payload(
        inputs,
        "verified_round",
    )

    if round_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose dataset freeze received a round from another project")

    round_id = str(round_payload.get("round_id") or "")

    if not round_id:
        raise ValidationError("Pose dataset freeze requires a verified Active Learning round")

    service = PoseTrainingDatasetService(session)

    dataset = service.create_from_round(
        round_id,
        PoseTrainingDatasetCreateRequest(
            name=(str(parameters["name"]) if parameters.get("name") else None),
            created_by=str(
                parameters.get(
                    "created_by",
                    "workflow",
                )
            ),
        ),
    )

    if dataset.project_id != project_id:
        raise ValidationError("Frozen pose dataset belongs to another project")

    return [
        {
            "port_id": "dataset",
            "data_type": "pose_training_dataset",
            "payload": {
                "schema_version": ("pose-training-dataset-workflow-0001"),
                "project_id": project_id,
                "dataset_id": dataset.id,
                "source_round_id": (dataset.source_round_id),
                "manifest_sha256": (dataset.manifest_sha256),
                "item_count": dataset.item_count,
                "pose_schema_id": (dataset.pose_schema_id),
                "pose_schema_revision": (dataset.pose_schema_revision),
                "pose_schema_content_hash": (dataset.pose_schema_content_hash),
                "truth_policy": ("scientist_verified_only"),
            },
        }
    ]


def execute_pose_training_export_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    dataset_payload = _single_payload(
        inputs,
        "dataset",
    )

    if dataset_payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose Training Export received a dataset from another project")

    dataset_id = str(dataset_payload.get("dataset_id") or "")

    if not dataset_id:
        raise ValidationError("Pose Training Export requires a frozen dataset")

    project = session.get(
        Project,
        project_id,
    )

    if project is None:
        raise ValidationError("Pose Training Export project was not found")

    export_format = str(
        parameters.get(
            "format",
            "native",
        )
    )

    if export_format == "native":
        (
            filename,
            content,
            bundle_sha256,
        ) = PoseTrainingDatasetService(session).native_package(dataset_id)

        media_type = "application/zip"
        lossy = False

    else:
        if export_format not in _EXTERNAL_POSE_EXPORT_FORMATS:
            raise ValidationError(f"Unsupported pose training export: {export_format}")

        artifact = PoseTrainingExportService(
            session,
            settings,
        ).export(
            dataset_id,
            cast(
                PoseTrainingExportFormat,
                export_format,
            ),
        )

        filename = artifact.filename
        content = artifact.content
        bundle_sha256 = artifact.bundle_sha256
        media_type = artifact.media_type
        lossy = artifact.lossy

    workflow_run_id = str(parameters.get("__workflow_run_id") or "unscoped")

    workflow_node_run_id = str(parameters.get("__workflow_node_run_id") or "unscoped")

    # Keep the user-facing/original export filename in provenance,
    # but use a compact physical storage name. Workflow run/node UUIDs
    # plus the long native export filename can exceed the classic
    # Windows MAX_PATH limit in deeply nested data roots (especially
    # pytest temp roots).
    storage_extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"

    if not storage_extension.isalnum() or len(storage_extension) > 10:
        storage_extension = "bin"

    storage_filename = f"pose-{workflow_node_run_id[:8]}.{storage_extension}"

    relative_path = f"{project.storage_root}/derived/workflows/{workflow_run_id}/{storage_filename}"

    destination = resolve_managed_project_path(
        settings,
        relative_path,
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.write_bytes(content)

    return [
        {
            "port_id": "package",
            "data_type": "pose_training_package",
            "payload": {
                "schema_version": ("pose-training-package-workflow-0001"),
                "project_id": project_id,
                "dataset_id": dataset_id,
                "export_format": export_format,
                "filename": filename,
                "storage_filename": storage_filename,
                "media_type": media_type,
                "lossy": lossy,
                "bundle_sha256": (bundle_sha256),
                "size_bytes": len(content),
                "managed_path": relative_path,
                "workflow_run_id": (workflow_run_id),
                "workflow_node_run_id": (workflow_node_run_id),
            },
        }
    ]


def execute_pose_review_gate_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters

    source = runtime_adapters._single_artifact(
        inputs,
        "tracks",
    )

    payload = dict(source.payload_json or {})

    if payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose Review received tracks from another project")

    node_run = runtime_adapters._current_review_node(
        session,
        source,
        "pose_review_gate",
    )

    readiness = pose_temporal_review_status(
        session,
        source,
        project_id=project_id,
    )

    approval = dict((node_run.result_json or {}).get("review_approval") or {})

    if not approval:
        raise WorkflowReviewRequired(
            f"{node_run.node_id} is waiting for scientist pose review",
            details={
                "node_run_id": node_run.id,
                "node_id": node_run.node_id,
                "node_type": node_run.node_type,
                "source_artifact_id": source.id,
                "source_data_type": source.data_type,
                "review_workspace": "pose_annotation_editor",
                "track_ids": readiness["track_ids"],
                "review_readiness": readiness,
            },
        )

    if not readiness["ready"]:
        raise ValidationError(
            "Pose Review approval is no longer valid because "
            "the canonical temporal pose state has unresolved blockers"
        )

    return [
        {
            "port_id": "poses",
            "data_type": "reviewed_pose_tracks",
            "payload": {
                "schema_version": ("reviewed-pose-tracks-workflow-0001"),
                "project_id": project_id,
                "video_id": payload.get("video_id"),
                "video_sha256": payload.get("video_sha256"),
                "track_ids": readiness["track_ids"],
                "count": readiness["track_count"],
                "track_revisions": (readiness["current_track_revisions"]),
                "source_temporal_artifact_id": (source.id),
                "source_temporal_artifact_sha256": (source.payload_sha256),
                "review_approval": approval,
                "review_readiness": readiness,
                "truth_status": "scientist_reviewed",
            },
        }
    ]


def execute_pose_active_learning_review_gate_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters

    source = runtime_adapters._single_artifact(
        inputs,
        "round",
    )

    payload = dict(source.payload_json or {})

    if payload.get("project_id") not in {
        None,
        project_id,
    }:
        raise ValidationError("Pose Active Learning Review received a round from another project")

    node_run = runtime_adapters._current_review_node(
        session,
        source,
        "pose_active_learning_review_gate",
    )

    readiness = pose_active_learning_review_status(
        session,
        source,
        project_id=project_id,
    )

    approval = dict((node_run.result_json or {}).get("review_approval") or {})

    if not approval:
        raise WorkflowReviewRequired(
            f"{node_run.node_id} is waiting for scientist Active Learning review",
            details={
                "node_run_id": node_run.id,
                "node_id": node_run.node_id,
                "node_type": node_run.node_type,
                "source_artifact_id": source.id,
                "source_data_type": source.data_type,
                "review_workspace": "pose_annotation_editor",
                "round_id": readiness["round_id"],
                "review_readiness": readiness,
            },
        )

    if not readiness["ready"]:
        raise ValidationError(
            "Pose Active Learning approval is no longer valid because "
            "the round is not retraining-ready"
        )

    return [
        {
            "port_id": "verified_round",
            "data_type": ("verified_pose_active_learning_round"),
            "payload": {
                "schema_version": ("verified-pose-active-learning-workflow-0001"),
                "project_id": project_id,
                "video_id": readiness["video_id"],
                "round_id": readiness["round_id"],
                "selection_sha256": (readiness["selection_sha256"]),
                "selection_algorithm": (readiness["selection_algorithm"]),
                "selection_algorithm_version": (readiness["selection_algorithm_version"]),
                "verified_candidate_count": (readiness["verified_candidate_count"]),
                "skipped_candidate_count": (readiness["skipped_candidate_count"]),
                "retraining_ready": True,
                "source_round_artifact_id": (source.id),
                "source_round_artifact_sha256": (source.payload_sha256),
                "review_approval": approval,
                "review_readiness": readiness,
                "truth_policy": ("scientist_verified_only"),
            },
        }
    ]


_POSE_ADAPTERS = {
    "pose_inference": (execute_pose_inference_adapter),
    "pose_temporal_association": (execute_pose_temporal_association_adapter),
    "behavior_dynamics": (execute_behavior_dynamics_adapter),
    "pose_active_learning": (execute_pose_active_learning_adapter),
    "pose_review_gate": (execute_pose_review_gate_adapter),
    "pose_active_learning_review_gate": (execute_pose_active_learning_review_gate_adapter),
    "pose_training_dataset_freeze": (execute_pose_training_dataset_freeze_adapter),
    "pose_training_export": (execute_pose_training_export_adapter),
}


def register_pose_workflow_adapters() -> None:
    """Install Phase 10 pose adapters in the shared workflow runtime."""

    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.update(_POSE_ADAPTERS)

    runtime_adapters._ADAPTERS.update(_POSE_ADAPTERS)
