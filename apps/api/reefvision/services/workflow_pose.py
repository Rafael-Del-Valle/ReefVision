"""Workflow adapters over ReefVision's canonical pose science services."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseEventDetectionRun,
    PoseIdentityAssociationRun,
    PoseIdentityEvaluationRun,
    PoseMeasurementRun,
    PoseMeasurementSeries,
    Project,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.pose_biological_measurement import process_pose_biological_measurement_job
from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.schemas.behavior_dynamics import BehaviorDynamicsRequest
from reefvision.schemas.pose_active_learning import (
    PoseActiveLearningRoundCreateRequest,
)
from reefvision.schemas.pose_biological_measurement import (
    CycleDefinition,
    EventDetectionCreateRequest,
    MeasurementDefinition,
    PoseMeasurementRunCreateRequest,
)
from reefvision.schemas.pose_identity_tracking import (
    PoseIdentityAssociationCreateRequest,
    PoseIdentityAssociationParameters,
    PoseIdentityEvaluationRequest,
    PoseIdentityEvaluationResponse,
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
from reefvision.services.pose_biological_measurement import PoseBiologicalMeasurementService
from reefvision.services.pose_identity_tracking import PoseIdentityTrackingService
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
    biological_event_review_status,
    pose_active_learning_review_status,
    pose_identity_review_status,
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
    "pose_identity_association",
    "pose_identity_review_gate",
    "pose_identity_evaluation",
    "pose_identity_export",
    "anatomical_measurement",
    "biological_event_detection",
    "biological_event_review_gate",
    "biological_movement_export",
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


def _reusable_pose_tracking_job(
    session: Session,
    *,
    project_id: str,
    workflow_run_id: str | None,
    workflow_node_run_id: str | None,
    video_id: str,
    model_id: str,
) -> Job | None:
    """Reuse completed child tracking work after a workflow-node retry."""

    if not workflow_run_id or not workflow_node_run_id:
        return None

    candidates = list(
        session.scalars(
            select(Job)
            .where(
                Job.project_id == project_id,
                Job.job_type == "video_tracking",
            )
            .order_by(
                Job.created_at.desc(),
                Job.id,
            )
        )
    )

    for candidate in candidates:
        request = dict(candidate.request_json or {})

        if (
            str(request.get("workflow_run_id") or "") != workflow_run_id
            or str(request.get("workflow_node_run_id") or "") != workflow_node_run_id
        ):
            continue

        if (
            str(request.get("video_id") or "") != video_id
            or str(request.get("model_id") or "") != model_id
        ):
            raise ValidationError(
                "A recovered pose-inference node references "
                "different video/model inputs than its persisted child job"
            )

        if candidate.status == "succeeded":
            return candidate

    return None


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

    reusable_child_job = _reusable_pose_tracking_job(
        session,
        project_id=project_id,
        workflow_run_id=(str(workflow_run_id) if workflow_run_id else None),
        workflow_node_run_id=(str(workflow_node_run_id) if workflow_node_run_id else None),
        video_id=video.id,
        model_id=model.id,
    )

    if reusable_child_job is None:
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
    else:
        child_job = reusable_child_job

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


def _identity_schema_binding(
    tracks: list[VideoTrack], pose_payload: dict[str, Any]
) -> tuple[str, int, str]:
    raw_schema = pose_payload.get("pose_schema")
    schema = dict(raw_schema) if isinstance(raw_schema, dict) else {}
    if not schema and tracks:
        schema = dict((tracks[0].metadata_json or {}).get("pose_landmark_schema") or {})
    schema_id = str(schema.get("schema_id") or schema.get("id") or "")
    revision = int(schema.get("schema_revision") or schema.get("revision") or 0)
    content_hash = str(schema.get("content_hash") or schema.get("content_sha256") or "")
    if not schema_id or revision < 1 or len(content_hash) != 64:
        raise ValidationError(
            "Identity association requires pose schema ID, revision, and content hash"
        )
    return schema_id, revision, content_hash


def execute_pose_identity_association_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    pose_payload = _single_payload(inputs, "poses")
    if pose_payload.get("project_id") not in {None, project_id}:
        raise ValidationError("Identity association received pose tracks from another project")
    track_ids = _track_ids(pose_payload)
    tracks, video = _scoped_tracks(session, project_id=project_id, track_ids=track_ids)
    schema_id, schema_revision, schema_hash = _identity_schema_binding(tracks, pose_payload)
    association_parameters = PoseIdentityAssociationParameters(
        max_gap_frames=int(parameters.get("max_gap_frames", 5)),
        max_normalized_distance=float(parameters.get("max_normalized_distance", 1.5)),
        minimum_iou=float(parameters.get("minimum_iou", 0.0)),
        minimum_landmark_similarity=float(parameters.get("minimum_landmark_similarity", 0.0)),
        minimum_detection_confidence=float(parameters.get("minimum_detection_confidence", 0.05)),
        acceptance_threshold=float(parameters.get("acceptance_threshold", 0.75)),
        low_confidence_threshold=float(parameters.get("low_confidence_threshold", 0.6)),
        proximity_weight=float(parameters.get("proximity_weight", 0.35)),
        overlap_weight=float(parameters.get("overlap_weight", 0.2)),
        landmark_weight=float(parameters.get("landmark_weight", 0.25)),
        motion_weight=float(parameters.get("motion_weight", 0.2)),
        confidence_weight=float(parameters.get("confidence_weight", 0.1)),
    )
    service = PoseIdentityTrackingService(session)
    child = service.submit(
        project_id,
        PoseIdentityAssociationCreateRequest(
            video_id=video.id,
            source_track_ids=track_ids,
            pose_schema_id=schema_id,
            pose_schema_revision=schema_revision,
            pose_schema_content_hash=schema_hash,
            parameters=association_parameters,
            device=str(parameters.get("device", "auto")),
        ),
    )
    child_record = session.get(Job, child.id)
    if child_record is None:
        raise ValidationError("Identity association child job disappeared before execution")
    child_record.request_json = {
        **dict(child_record.request_json or {}),
        "workflow_run_id": str(parameters.get("__workflow_run_id") or ""),
        "workflow_node_run_id": str(parameters.get("__workflow_node_run_id") or ""),
    }
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    process_pose_identity_tracking_job(settings, factory, child.id)
    session.expire_all()
    child_record = session.get(Job, child.id)
    if child_record is None or child_record.status != "completed":
        message = child_record.error_message if child_record is not None else "job disappeared"
        raise ValidationError(f"Identity association failed: {message}")
    run_id = str((child_record.result_json or {}).get("run_id") or "")
    run = service.get(run_id)
    return [
        {
            "port_id": "tracks",
            "data_type": "pose_identity_tracks",
            "payload": {
                "schema_version": "pose-identity-workflow-0001",
                "project_id": project_id,
                "video_id": video.id,
                "video_sha256": video.sha256,
                "run_id": run.id,
                "run_revision": run.revision,
                "association_job_id": child.id,
                "track_ids": track_ids,
                "pose_schema_id": run.pose_schema_id,
                "pose_schema_revision": run.pose_schema_revision,
                "pose_schema_content_hash": run.pose_schema_content_hash,
                "parameters": run.parameters_json,
                "parameters_sha256": run.parameters_sha256,
                "input_manifest_sha256": run.input_manifest_sha256,
                "coordinate_space": run.source_coordinate_space,
                "truth_status": "model_generated_unreviewed",
            },
        }
    ]


def execute_pose_identity_review_gate_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters
    source = runtime_adapters._single_artifact(inputs, "tracks")
    payload = dict(source.payload_json or {})
    node_run = runtime_adapters._current_review_node(session, source, "pose_identity_review_gate")
    readiness = pose_identity_review_status(session, source, project_id=project_id)
    approval = dict((node_run.result_json or {}).get("review_approval") or {})
    if not approval:
        raise WorkflowReviewRequired(
            f"{node_run.node_id} is waiting for scientist identity review",
            details={
                "node_run_id": node_run.id,
                "node_id": node_run.node_id,
                "node_type": node_run.node_type,
                "source_artifact_id": source.id,
                "review_workspace": "video_tracking_identity_review",
                "run_id": readiness["run_id"],
                "review_readiness": readiness,
            },
        )
    if not readiness["ready"]:
        raise ValidationError(
            "Identity Review approval is stale or current observations remain unreviewed"
        )
    return [
        {
            "port_id": "tracks",
            "data_type": "reviewed_pose_identity_tracks",
            "payload": {
                **payload,
                "schema_version": "reviewed-pose-identity-workflow-0001",
                "run_revision": readiness["current_run_revision"],
                "source_identity_artifact_id": source.id,
                "source_identity_artifact_sha256": source.payload_sha256,
                "review_approval": approval,
                "review_readiness": readiness,
                "truth_status": "scientist_reviewed",
            },
        }
    ]


def execute_pose_identity_evaluation_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    reviewed = _single_payload(inputs, "tracks")
    if reviewed.get("project_id") not in {None, project_id}:
        raise ValidationError("Identity evaluation received tracks from another project")
    run_id = str(reviewed.get("run_id") or "")
    run = session.get(PoseIdentityAssociationRun, run_id)
    if run is None:
        raise ValidationError("Identity evaluation association run was not found")
    if int(reviewed.get("run_revision") or 0) != run.revision:
        raise ValidationError(
            "Identity review artifact is stale; review the latest association revision"
        )
    evaluation = PoseIdentityTrackingService(session).evaluate(
        run_id,
        PoseIdentityEvaluationRequest(
            truth_dataset_id=str(parameters.get("truth_dataset_id") or ""),
            spatial_iou_threshold=float(parameters.get("spatial_iou_threshold", 0.5)),
        ),
    )
    return [
        {
            "port_id": "evaluation",
            "data_type": "pose_identity_evaluation",
            "payload": {
                "schema_version": "pose-identity-evaluation-workflow-0001",
                "project_id": project_id,
                "video_id": reviewed.get("video_id"),
                "run_id": run_id,
                "run_revision": evaluation.association_run_revision,
                "evaluation_id": evaluation.id,
                "truth_dataset_id": evaluation.truth_dataset_id,
                "result_sha256": evaluation.result_sha256,
                "metrics": evaluation.metrics_json,
                "warnings": evaluation.warnings_json,
                "provenance": evaluation.provenance_json,
            },
        }
    ]


def execute_pose_identity_export_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    evaluation = _single_payload(inputs, "evaluation")
    if evaluation.get("project_id") not in {None, project_id}:
        raise ValidationError("Identity export received an evaluation from another project")
    run_id = str(evaluation.get("run_id") or "")
    evaluation_id = str(evaluation.get("evaluation_id") or "")
    evaluation_record = session.get(PoseIdentityEvaluationRun, evaluation_id)
    if evaluation_record is None or evaluation_record.association_run_id != run_id:
        raise ValidationError("Identity evaluation artifact does not reference a valid report")
    if evaluation_record.result_sha256 != str(evaluation.get("result_sha256") or ""):
        raise ValidationError("Identity evaluation artifact integrity hash does not match")
    run = session.get(PoseIdentityAssociationRun, run_id)
    if run is None:
        raise ValidationError("Identity export association run was not found")
    if (
        evaluation_record.association_run_revision != int(evaluation.get("run_revision") or 0)
        or run.revision != evaluation_record.association_run_revision
    ):
        raise ValidationError(
            "Identity evaluation is stale; evaluate the latest association revision before export"
        )
    evaluation_report = PoseIdentityEvaluationResponse.model_validate(evaluation_record).model_dump(
        mode="json"
    )
    export_format = str(parameters.get("format", "json"))
    service = PoseIdentityTrackingService(session)
    if export_format == "json":
        content = json.dumps(
            {
                "schema_version": "pose-identity-evaluated-export-0001",
                "identity_results": service.export_json(run_id),
                "evaluation": evaluation_report,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        extension = "json"
        media_type = "application/json"
    elif export_format == "csv":
        content = service.export_csv(run_id).encode("utf-8")
        extension = "csv"
        media_type = "text/csv"
    else:
        raise ValidationError("Identity export format must be json or csv")
    project = session.get(Project, project_id)
    if project is None:
        raise ValidationError("Identity export project was not found")
    workflow_run_id = str(parameters.get("__workflow_run_id") or "unscoped")
    node_run_id = str(parameters.get("__workflow_node_run_id") or "unscoped")
    relative_path = (
        f"{project.storage_root}/derived/workflows/{workflow_run_id}/"
        f"identity-{node_run_id[:8]}.{extension}"
    )
    destination = resolve_managed_project_path(settings, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return [
        {
            "port_id": "package",
            "data_type": "pose_identity_package",
            "payload": {
                "schema_version": "pose-identity-package-workflow-0001",
                "project_id": project_id,
                "run_id": run_id,
                "run_revision": evaluation.get("run_revision"),
                "evaluation_id": evaluation.get("evaluation_id"),
                "evaluation_result_sha256": evaluation.get("result_sha256"),
                "evaluation_metrics": evaluation_report["metrics_json"],
                "evaluation_warnings": evaluation_report["warnings_json"],
                "evaluation_provenance": evaluation_report["provenance_json"],
                "format": export_format,
                "media_type": media_type,
                "managed_path": relative_path,
                "size_bytes": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "workflow_run_id": workflow_run_id,
                "workflow_node_run_id": node_run_id,
            },
        }
    ]


def execute_anatomical_measurement_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    reviewed = _single_payload(inputs, "tracks")
    run_id = str(reviewed.get("run_id") or "")
    identity_run = session.get(PoseIdentityAssociationRun, run_id)
    if identity_run is None or identity_run.project_id != project_id:
        raise ValidationError("Anatomical measurement identity run was not found")
    if identity_run.revision != int(reviewed.get("run_revision") or 0):
        raise ValidationError("Reviewed identity artifact is stale")
    raw_definitions = parameters.get("definitions")
    if not isinstance(raw_definitions, list) or not raw_definitions:
        raise ValidationError("Anatomical measurement requires at least one definition")
    definitions = [MeasurementDefinition.model_validate(item) for item in raw_definitions]
    service = PoseBiologicalMeasurementService(session)
    child = service.submit_measurements(
        project_id,
        PoseMeasurementRunCreateRequest(
            video_id=identity_run.video_id,
            source_identity_run_id=identity_run.id,
            source_identity_run_revision=identity_run.revision,
            definitions=definitions,
            maximum_gap_s=float(parameters.get("maximum_gap_s", 0.25)),
            verification_mode="scientific",
        ),
    )
    child_record = session.get(Job, child.id)
    if child_record is None:
        raise ValidationError("Measurement child job disappeared before execution")
    child_record.request_json = {
        **dict(child_record.request_json or {}),
        "workflow_run_id": str(parameters.get("__workflow_run_id") or ""),
        "workflow_node_run_id": str(parameters.get("__workflow_node_run_id") or ""),
    }
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    process_pose_biological_measurement_job(settings, factory, child.id)
    session.expire_all()
    child_record = session.get(Job, child.id)
    if child_record is None or child_record.status != "completed":
        message = child_record.error_message if child_record is not None else "job disappeared"
        raise ValidationError(f"Anatomical measurement failed: {message}")
    measurement_run_id = str((child_record.result_json or {}).get("run_id") or "")
    run = session.get(PoseMeasurementRun, measurement_run_id)
    if run is None:
        raise ValidationError("Completed measurement run disappeared")
    series = service.series(run.id)
    return [
        {
            "port_id": "measurements",
            "data_type": "pose_measurement_series",
            "payload": {
                "schema_version": "pose-measurement-workflow-0001",
                "project_id": project_id,
                "video_id": run.video_id,
                "measurement_run_id": run.id,
                "measurement_job_id": child.id,
                "source_identity_run_id": run.source_identity_run_id,
                "source_identity_run_revision": run.source_identity_run_revision,
                "input_manifest_sha256": run.input_manifest_sha256,
                "result_sha256": run.result_sha256,
                "series": [
                    {
                        "id": item.id,
                        "identity_id": item.animal_identity_id,
                        "definition_id": item.definition_id,
                        "series_sha256": item.series_sha256,
                    }
                    for item in series
                ],
                "truth_status": "derived_from_scientist_reviewed_identities",
            },
        }
    ]


def execute_biological_event_detection_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    measurement = _single_payload(inputs, "measurements")
    run_id = str(measurement.get("measurement_run_id") or "")
    run = session.get(PoseMeasurementRun, run_id)
    if run is None or run.project_id != project_id:
        raise ValidationError("Event detection measurement run was not found")
    if run.result_sha256 != str(measurement.get("result_sha256") or ""):
        raise ValidationError("Measurement workflow artifact integrity hash does not match")
    raw_cycles = parameters.get("cycles")
    if not isinstance(raw_cycles, list) or not raw_cycles:
        raise ValidationError("Biological event detection requires cycle definitions")
    available = list(
        session.scalars(
            select(PoseMeasurementSeries).where(PoseMeasurementSeries.measurement_run_id == run.id)
        )
    )
    cycles: list[CycleDefinition] = []
    for raw in raw_cycles:
        item = dict(raw)
        series_id = str(item.pop("measurement_series_id", ""))
        definition_id = str(item.pop("measurement_definition_id", ""))
        identity_id = str(item.pop("identity_id", ""))
        matches = [
            series
            for series in available
            if (series_id and series.id == series_id)
            or (
                not series_id
                and series.definition_id == definition_id
                and (not identity_id or series.animal_identity_id == identity_id)
            )
        ]
        if not matches:
            raise ValidationError("Cycle definition did not match a measurement series")
        cycles.extend(
            CycleDefinition(measurement_series_id=series.id, **item) for series in matches
        )
    service = PoseBiologicalMeasurementService(session)
    child = service.submit_events(
        project_id,
        EventDetectionCreateRequest(measurement_run_id=run.id, cycles=cycles),
    )
    child_record = session.get(Job, child.id)
    if child_record is None:
        raise ValidationError("Event-detection child job disappeared before execution")
    child_record.request_json = {
        **dict(child_record.request_json or {}),
        "workflow_run_id": str(parameters.get("__workflow_run_id") or ""),
        "workflow_node_run_id": str(parameters.get("__workflow_node_run_id") or ""),
    }
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    process_pose_biological_measurement_job(settings, factory, child.id)
    session.expire_all()
    child_record = session.get(Job, child.id)
    if child_record is None or child_record.status != "completed":
        message = child_record.error_message if child_record is not None else "job disappeared"
        raise ValidationError(f"Biological event detection failed: {message}")
    event_run_id = str((child_record.result_json or {}).get("run_id") or "")
    event_run = session.get(PoseEventDetectionRun, event_run_id)
    if event_run is None:
        raise ValidationError("Completed event-detection run disappeared")
    return [
        {
            "port_id": "events",
            "data_type": "pose_event_candidates",
            "payload": {
                "schema_version": "pose-biological-events-workflow-0001",
                "project_id": project_id,
                "video_id": run.video_id,
                "measurement_run_id": run.id,
                "measurement_result_sha256": run.result_sha256,
                "event_run_id": event_run.id,
                "event_job_id": child.id,
                "configuration_sha256": event_run.configuration_sha256,
                "result_sha256": event_run.result_sha256,
                "truth_status": "automated_unreviewed_candidates",
            },
        }
    ]


def execute_biological_event_review_gate_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters
    source = runtime_adapters._single_artifact(inputs, "events")
    payload = dict(source.payload_json or {})
    node_run = runtime_adapters._current_review_node(
        session, source, "biological_event_review_gate"
    )
    readiness = biological_event_review_status(session, source, project_id=project_id)
    approval = dict((node_run.result_json or {}).get("review_approval") or {})
    if not approval:
        raise WorkflowReviewRequired(
            f"{node_run.node_id} is waiting for scientist event review",
            details={
                "node_run_id": node_run.id,
                "node_id": node_run.node_id,
                "node_type": node_run.node_type,
                "source_artifact_id": source.id,
                "review_workspace": "biological_movement_review",
                "event_run_id": readiness["event_run_id"],
                "review_readiness": readiness,
            },
        )
    if not readiness["ready"]:
        raise ValidationError("Biological event review is incomplete or stale")
    return [
        {
            "port_id": "events",
            "data_type": "reviewed_pose_events",
            "payload": {
                **payload,
                "schema_version": "reviewed-pose-biological-events-workflow-0001",
                "source_event_artifact_id": source.id,
                "source_event_artifact_sha256": source.payload_sha256,
                "review_approval": approval,
                "review_readiness": readiness,
                "truth_status": "scientist_reviewed",
            },
        }
    ]


def execute_biological_movement_export_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    reviewed = _single_payload(inputs, "events")
    if reviewed.get("project_id") not in {None, project_id}:
        raise ValidationError("Biological movement export received another project's artifact")
    event_run_id = str(reviewed.get("event_run_id") or "")
    service = PoseBiologicalMeasurementService(session)
    export_format = str(parameters.get("format", "json"))
    if export_format == "json":
        content = json.dumps(
            service.export_json(event_run_id, reviewed_only=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        extension, media_type = "json", "application/json"
    elif export_format == "csv":
        content = service.export_csv(event_run_id, reviewed_only=True).encode("utf-8")
        extension, media_type = "csv", "text/csv"
    else:
        raise ValidationError("Biological movement export format must be json or csv")
    project = session.get(Project, project_id)
    if project is None:
        raise ValidationError("Biological movement export project was not found")
    workflow_run_id = str(parameters.get("__workflow_run_id") or "unscoped")
    node_run_id = str(parameters.get("__workflow_node_run_id") or "unscoped")
    relative_path = (
        f"{project.storage_root}/derived/workflows/{workflow_run_id}/"
        f"biological-movement-{node_run_id[:8]}.{extension}"
    )
    destination = resolve_managed_project_path(settings, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return [
        {
            "port_id": "package",
            "data_type": "biological_movement_package",
            "payload": {
                "schema_version": "biological-movement-package-workflow-0001",
                "project_id": project_id,
                "event_run_id": event_run_id,
                "measurement_run_id": reviewed.get("measurement_run_id"),
                "format": export_format,
                "media_type": media_type,
                "managed_path": relative_path,
                "size_bytes": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "workflow_run_id": workflow_run_id,
                "workflow_node_run_id": node_run_id,
                "truth_status": "scientist_reviewed",
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
    "pose_identity_association": (execute_pose_identity_association_adapter),
    "pose_identity_review_gate": (execute_pose_identity_review_gate_adapter),
    "pose_identity_evaluation": (execute_pose_identity_evaluation_adapter),
    "pose_identity_export": (execute_pose_identity_export_adapter),
    "anatomical_measurement": (execute_anatomical_measurement_adapter),
    "biological_event_detection": (execute_biological_event_detection_adapter),
    "biological_event_review_gate": (execute_biological_event_review_gate_adapter),
    "biological_movement_export": (execute_biological_movement_export_adapter),
}


def register_pose_workflow_adapters() -> None:
    """Install Phase 10 pose adapters in the shared workflow runtime."""

    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.update(_POSE_ADAPTERS)

    runtime_adapters._ADAPTERS.update(_POSE_ADAPTERS)
