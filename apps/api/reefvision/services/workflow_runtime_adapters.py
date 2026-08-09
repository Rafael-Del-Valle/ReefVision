"""Workflow-safe adapters around existing ReefVision production operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationPrediction,
    Job,
    ModelRegistration,
    PredictionProposal,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.classification_inference import process_classification_inference_job
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.services.mask_measurements import MaskMeasurementService

RUNTIME_ADAPTER_NODE_TYPES = {
    "segmentation_inference",
    "classification_inference",
    "mask_measurements",
    "video_tracking",
}


def _single_payload(
    inputs: dict[str, list[WorkflowArtifact]],
    port_id: str,
) -> dict[str, Any]:
    artifacts = inputs.get(port_id, [])
    if len(artifacts) != 1:
        raise ValidationError(f"Workflow input requires exactly one artifact: {port_id}")
    return dict(artifacts[0].payload_json)


def _child_factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def _run_child_job(
    session: Session,
    job: Job,
    processor: Any,
    settings: Settings,
) -> Job:
    session.add(job)
    session.commit()
    child_job_id = job.id
    processor(settings, _child_factory(session), child_job_id)
    session.expire_all()
    completed = session.get(Job, child_job_id)
    if completed is None or completed.status != "succeeded":
        detail = completed.error_message if completed is not None else "job disappeared"
        raise ValidationError(f"Workflow child job failed: {detail}")
    return completed


def _segmentation_inference(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    image_payload = _single_payload(inputs, "images")
    model_payload = _single_payload(inputs, "model")
    if image_payload.get("project_id") != project_id:
        raise ValidationError("Segmentation inference received a foreign image collection")
    image_ids = [str(value) for value in image_payload.get("image_ids", [])]
    if not image_ids:
        raise ValidationError("Segmentation inference requires at least one image")
    model_id = str(model_payload.get("model_id") or "")
    model = session.get(ModelRegistration, model_id)
    if model is None or model.project_id != project_id:
        raise ValidationError("Segmentation inference model does not belong to this project")
    if model.task not in {"segment", "semantic_segment"}:
        raise ValidationError("Segmentation Inference requires an instance or semantic segmenter")

    job = _run_child_job(
        session,
        Job(
            project_id=project_id,
            job_type="inference",
            status="queued",
            progress_current=0,
            progress_total=len(image_ids),
            request_json={
                "model_id": model.id,
                "image_ids": image_ids,
                "confidence_threshold": float(parameters.get("confidence", 0.25)),
                "iou_threshold": float(parameters.get("iou", 0.5)),
                "device": str(parameters.get("device", "auto")),
                "model_task": model.task,
                "created_by_workflow": True,
            },
            result_json={"stage": "queued", "created_by_workflow": True},
        ),
        process_inference_job,
        settings,
    )
    proposals = list(
        session.scalars(
            select(PredictionProposal)
            .where(PredictionProposal.inference_job_id == job.id)
            .order_by(
                PredictionProposal.image_id,
                PredictionProposal.created_at,
                PredictionProposal.id,
            )
        )
    )
    masks = [
        {
            "proposal_id": proposal.id,
            "image_id": proposal.image_id,
            "label_class_id": proposal.label_class_id,
            "predicted_label": proposal.predicted_label,
            "predicted_index": proposal.predicted_index,
            "confidence": proposal.confidence,
            "geometry_kind": proposal.geometry_kind,
            "polygon": proposal.polygon_json,
            "mask_path": proposal.mask_path,
            "mask_content_sha256": proposal.mask_content_sha256,
            "box": {
                "x_min": proposal.x_min,
                "y_min": proposal.y_min,
                "x_max": proposal.x_max,
                "y_max": proposal.y_max,
            },
            "provenance": dict(proposal.provenance_json or {}),
        }
        for proposal in proposals
        if proposal.geometry_kind in {"polygon_mask", "raster_mask"}
    ]
    return [
        {
            "port_id": "proposals",
            "data_type": "mask_proposals",
            "payload": {
                "schema_version": "mask-proposals-0001",
                "project_id": project_id,
                "source_id": model.id,
                "source_kind": "registered_model",
                "source_model_id": model.id,
                "source_model_sha256": model.sha256,
                "provider_name": model.provider_name,
                "provider_version": model.provider_version,
                "inference_job_id": job.id,
                "image_ids": image_ids,
                "proposal_ids": [item["proposal_id"] for item in masks],
                "count": len(masks),
                "masks": masks,
            },
        }
    ]


def _classification_inference(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    image_payload = _single_payload(inputs, "images")
    model_payload = _single_payload(inputs, "model")
    if image_payload.get("project_id") != project_id:
        raise ValidationError("Classification inference received a foreign image collection")
    image_ids = [str(value) for value in image_payload.get("image_ids", [])]
    if not image_ids:
        raise ValidationError("Classification inference requires at least one image")
    model_id = str(model_payload.get("model_id") or "")
    model = session.get(ModelRegistration, model_id)
    if model is None or model.project_id != project_id:
        raise ValidationError("Classification model does not belong to this project")
    if model.purpose != "classifier" or model.task != "classify":
        raise ValidationError("Classification Inference requires a classifier model")
    label_set = str(parameters.get("label_set") or "default")
    top_k = int(parameters.get("top_k", 5))

    job = _run_child_job(
        session,
        Job(
            project_id=project_id,
            job_type="classification_inference",
            status="queued",
            progress_current=0,
            progress_total=len(image_ids),
            request_json={
                "model_id": model.id,
                "image_ids": image_ids,
                "label_set": label_set,
                "top_k": top_k,
                "device": str(parameters.get("device", "auto")),
                "created_by_workflow": True,
            },
            result_json={"stage": "queued", "created_by_workflow": True},
        ),
        process_classification_inference_job,
        settings,
    )
    predictions = list(
        session.scalars(
            select(ClassificationPrediction)
            .where(
                ClassificationPrediction.project_id == project_id,
                ClassificationPrediction.model_id == model.id,
                ClassificationPrediction.image_id.in_(image_ids),
                ClassificationPrediction.label_set == label_set,
                ClassificationPrediction.status == "pending",
            )
            .order_by(
                ClassificationPrediction.image_id,
                ClassificationPrediction.rank,
                ClassificationPrediction.created_at,
                ClassificationPrediction.id,
            )
        )
    )
    return [
        {
            "port_id": "predictions",
            "data_type": "classification_predictions",
            "payload": {
                "schema_version": "classification-predictions-0001",
                "project_id": project_id,
                "source_id": model.id,
                "source_kind": "registered_model",
                "source_model_id": model.id,
                "source_model_sha256": model.sha256,
                "provider_name": model.provider_name,
                "provider_version": model.provider_version,
                "inference_job_id": job.id,
                "label_set": label_set,
                "top_k": top_k,
                "image_ids": image_ids,
                "prediction_ids": [prediction.id for prediction in predictions],
                "count": len(predictions),
                "predictions": [
                    {
                        "prediction_id": prediction.id,
                        "image_id": prediction.image_id,
                        "label_class_id": prediction.label_class_id,
                        "confidence": prediction.confidence,
                        "rank": prediction.rank,
                        "scores": dict(prediction.scores_json or {}),
                    }
                    for prediction in predictions
                ],
            },
        }
    ]


def _mask_measurements(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    mask_payload = _single_payload(inputs, "masks")
    if mask_payload.get("project_id") != project_id:
        raise ValidationError("Mask Measurements received masks from another project")
    mask_ids = [str(value) for value in mask_payload.get("mask_annotation_ids", [])]
    measurement_service = MaskMeasurementService(session, settings)
    rows = [measurement_service.measure(mask_id).model_dump(mode="json") for mask_id in mask_ids]
    return [
        {
            "port_id": "measurements",
            "data_type": "measurement_table",
            "payload": {
                "schema_version": "measurement-table-0001",
                "project_id": project_id,
                "mask_annotation_ids": mask_ids,
                "count": len(rows),
                "profile": str(parameters.get("profile", "default")),
                "rows": rows,
            },
        }
    ]


def _video_tracking(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    video_payload = _single_payload(inputs, "video")
    model_payload = _single_payload(inputs, "model")
    video_id = str(video_payload.get("video_id") or "")
    model_id = str(model_payload.get("model_id") or "")
    video = session.get(VideoAsset, video_id)
    model = session.get(ModelRegistration, model_id)
    if video is None or video.project_id != project_id:
        raise ValidationError("Video Tracking requires a video from this project")
    if model is None or model.project_id != project_id:
        raise ValidationError("Video Tracking requires a model from this project")
    if model.purpose not in {"detector", "segmenter"} or model.task not in {
        "detect",
        "segment",
    }:
        raise ValidationError("Video Tracking requires a detection or instance model")

    job = _run_child_job(
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
                "tracker": str(parameters.get("tracker", "bytetrack.yaml")),
                "confidence": float(parameters.get("confidence", 0.25)),
                "iou": float(parameters.get("iou", 0.5)),
                "minimum_track_frames": int(parameters.get("minimum_track_frames", 2)),
                "device": str(parameters.get("device", "auto")),
                "created_by_workflow": True,
            },
            result_json={"stage": "queued", "created_by_workflow": True},
        ),
        process_video_tracking_job,
        settings,
    )
    tracks = list(
        session.scalars(
            select(VideoTrack)
            .where(
                VideoTrack.video_id == video.id,
                VideoTrack.source_job_id == job.id,
                VideoTrack.deleted_at.is_(None),
            )
            .order_by(VideoTrack.track_number, VideoTrack.id)
        )
    )
    return [
        {
            "port_id": "tracks",
            "data_type": "video_tracks",
            "payload": {
                "schema_version": "video-tracks-0001",
                "project_id": project_id,
                "video_id": video.id,
                "source_model_id": model.id,
                "source_model_sha256": model.sha256,
                "tracking_job_id": job.id,
                "tracker": str(parameters.get("tracker", "bytetrack.yaml")),
                "track_ids": [track.id for track in tracks],
                "count": len(tracks),
                "tracks": [
                    {
                        "track_id": track.id,
                        "label_class_id": track.label_class_id,
                        "track_number": track.track_number,
                        "geometry_kind": track.geometry_kind,
                        "keyframes": list(track.keyframes_json or []),
                        "interpolation": track.interpolation,
                        "status": track.status,
                        "metadata": dict(track.metadata_json or {}),
                    }
                    for track in tracks
                ],
            },
        }
    ]


_ADAPTERS = {
    "segmentation_inference": _segmentation_inference,
    "classification_inference": _classification_inference,
    "mask_measurements": _mask_measurements,
    "video_tracking": _video_tracking,
}


def execute_runtime_adapter(
    node_type: str,
    *,
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    adapter = _ADAPTERS.get(node_type)
    if adapter is None:
        raise ValidationError(f"Workflow runtime adapter is unavailable: {node_type}")
    return adapter(session, settings, project_id, parameters, inputs)
