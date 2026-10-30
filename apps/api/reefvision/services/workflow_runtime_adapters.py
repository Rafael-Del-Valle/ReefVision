"""Workflow-safe adapters around existing ReefVision production operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationPrediction,
    ImageAsset,
    Job,
    LabelClass,
    ModelRegistration,
    PredictionProposal,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
    WorkflowNodeRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.jobs.classification_inference import process_classification_inference_job
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.services.mask_measurements import MaskMeasurementService
from reefvision.services.workflow_depth import create_depth_map_artifacts
from reefvision.services.workflow_prompt_assist import create_prompt_assist_mask_proposals
from reefvision.services.workflow_review import WorkflowReviewRequired
from reefvision.services.workflow_vlm import VlmClassDefinition, run_vlm_detection
from reefvision.storage.projects import resolve_managed_project_path

RUNTIME_ADAPTER_NODE_TYPES = {
    "segmentation_inference",
    "classification_inference",
    "vlm_detection",
    "detection_review_gate",
    "mask_review_gate",
    "classification_review_gate",
    "prompt_assist_masks",
    "relative_depth_estimation",
    "mask_measurements",
    "video_tracking",
    "ecology_longitudinal_analysis",
    "ecology_identity_registry_source",
    "ecology_connected_branch_preview",
    "ecology_measurement_csv_export",
    "ecology_population_csv_export",
    "ecology_paired_count_comparison",
    "ecology_paired_count_csv_export",
}


def _single_artifact(
    inputs: dict[str, list[WorkflowArtifact]],
    port_id: str,
) -> WorkflowArtifact:
    artifacts = inputs.get(port_id, [])
    if len(artifacts) != 1:
        raise ValidationError(f"Workflow input requires exactly one artifact: {port_id}")
    return artifacts[0]


def _single_payload(
    inputs: dict[str, list[WorkflowArtifact]],
    port_id: str,
) -> dict[str, Any]:
    return dict(_single_artifact(inputs, port_id).payload_json)


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


def _vlm_detection(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    image_payload = _single_payload(inputs, "images")
    if image_payload.get("project_id") != project_id:
        raise ValidationError("Cloud VLM Detection received a foreign image collection")
    image_ids = [str(value) for value in image_payload.get("image_ids", [])]
    if not image_ids:
        raise ValidationError("Cloud VLM Detection requires at least one image")

    provider = str(parameters.get("provider") or "").strip().lower()
    model = str(parameters.get("model") or "").strip()
    prompt = str(
        parameters.get("prompt") or "Detect every visible instance of the selected classes."
    ).strip()
    requested_class_ids = [str(value) for value in parameters.get("label_class_ids", [])]
    if not requested_class_ids:
        raise ValidationError("Cloud VLM Detection requires label_class_ids")

    class_rows = list(
        session.scalars(
            select(LabelClass).where(
                LabelClass.project_id == project_id,
                LabelClass.id.in_(requested_class_ids),
            )
        )
    )
    classes_by_id = {item.id: item for item in class_rows}
    if set(classes_by_id) != set(requested_class_ids):
        raise ValidationError("Every Cloud VLM Detection class must belong to this project")
    classes = [
        VlmClassDefinition(
            label_class_id=classes_by_id[class_id].id,
            name=classes_by_id[class_id].name,
            scientific_name=classes_by_id[class_id].scientific_name,
            state_name=classes_by_id[class_id].state_name,
            description=classes_by_id[class_id].description,
        )
        for class_id in requested_class_ids
    ]

    image_rows = list(
        session.scalars(
            select(ImageAsset).where(
                ImageAsset.project_id == project_id,
                ImageAsset.id.in_(image_ids),
            )
        )
    )
    images_by_id = {item.id: item for item in image_rows}
    if set(images_by_id) != set(image_ids):
        raise ValidationError("Every Cloud VLM Detection image must belong to this project")

    detections: list[dict[str, Any]] = []
    usage_by_image: dict[str, dict[str, Any]] = {}
    response_ids: dict[str, str | None] = {}
    prompt_sha256: str | None = None
    schema_sha256: str | None = None
    for image_id in image_ids:
        image = images_by_id[image_id]
        managed_path = resolve_managed_project_path(settings, image.managed_path)
        if not managed_path.exists():
            raise ValidationError(f"Managed image file is missing: {image.id}")
        result = run_vlm_detection(
            settings,
            provider=provider,
            model=model,
            prompt=prompt,
            classes=classes,
            image_id=image.id,
            image_bytes=managed_path.read_bytes(),
            media_type=image.media_type,
            image_width=image.width_px,
            image_height=image.height_px,
        )
        prompt_sha256 = str(result["prompt_sha256"])
        schema_sha256 = str(result["schema_sha256"])
        usage_by_image[image.id] = dict(result.get("usage") or {})
        response_ids[image.id] = (
            str(result["response_id"]) if result.get("response_id") is not None else None
        )
        for detection in result["detections"]:
            detections.append(
                {
                    **dict(detection),
                    "provenance": {
                        "source": "cloud_vlm",
                        "provider": provider,
                        "model": model,
                        "response_id": response_ids[image.id],
                        "prompt_sha256": prompt_sha256,
                        "schema_sha256": schema_sha256,
                        "image_sha256": image.sha256,
                    },
                }
            )

    return [
        {
            "port_id": "proposals",
            "data_type": "detection_proposals",
            "payload": {
                "schema_version": "cloud-vlm-detection-proposals-0001",
                "project_id": project_id,
                "source_id": f"cloud-vlm:{provider}:{model}",
                "source_kind": "cloud_vlm",
                "provider_name": provider,
                "provider_model": model,
                "image_ids": image_ids,
                "image_sha256": {image_id: images_by_id[image_id].sha256 for image_id in image_ids},
                "label_class_ids": requested_class_ids,
                "prompt": prompt,
                "prompt_sha256": prompt_sha256,
                "schema_sha256": schema_sha256,
                "usage_by_image": usage_by_image,
                "response_ids": response_ids,
                "proposal_ids": [],
                "count": len(detections),
                "detections": detections,
                "credentials_persisted": False,
            },
        }
    ]


def _current_review_node(
    session: Session,
    source: WorkflowArtifact,
    node_type: str,
) -> WorkflowNodeRun:
    node_run = session.scalar(
        select(WorkflowNodeRun).where(
            WorkflowNodeRun.workflow_run_id == source.workflow_run_id,
            WorkflowNodeRun.node_type == node_type,
            WorkflowNodeRun.status == "running",
        )
    )
    if node_run is None:
        raise ValidationError("The active workflow review node could not be resolved")
    return node_run


def _review_gate(
    session: Session,
    project_id: str,
    inputs: dict[str, list[WorkflowArtifact]],
    *,
    node_type: str,
    input_port: str,
    output_port: str,
    output_type: str,
) -> list[dict[str, Any]]:
    source = _single_artifact(inputs, input_port)
    payload = dict(source.payload_json or {})
    if payload.get("project_id") != project_id:
        raise ValidationError("Human Review received artifacts from another project")
    node_run = _current_review_node(session, source, node_type)
    approval = dict((node_run.result_json or {}).get("review_approval") or {})
    if not approval:
        item_count = int(payload.get("count", 0) or 0)
        raise WorkflowReviewRequired(
            f"{node_run.node_id} is waiting for human review",
            details={
                "node_run_id": node_run.id,
                "node_id": node_run.node_id,
                "node_type": node_type,
                "source_artifact_id": source.id,
                "source_data_type": source.data_type,
                "item_count": item_count,
            },
        )

    reviewed_payload: dict[str, Any] = {
        "schema_version": "workflow-reviewed-artifact-0001",
        "project_id": project_id,
        "source_artifact_id": source.id,
        "source_data_type": source.data_type,
        "review_approval": approval,
    }
    if source.data_type in {"detection_proposals", "mask_proposals"}:
        proposal_ids = [str(value) for value in payload.get("proposal_ids", [])]
        proposals = list(
            session.scalars(
                select(PredictionProposal).where(PredictionProposal.id.in_(proposal_ids))
            )
        )
        pending = [item.id for item in proposals if item.review_status == "pending"]
        if pending:
            raise WorkflowReviewRequired(
                f"{len(pending)} model prediction(s) still require review",
                details={
                    "node_run_id": node_run.id,
                    "pending_prediction_ids": pending,
                },
            )
        accepted = [
            item for item in proposals if item.review_status in {"accepted", "edited_and_accepted"}
        ]
        reviewed_payload.update(
            {
                "accepted_proposal_ids": [item.id for item in accepted],
                "rejected_proposal_ids": [
                    item.id for item in proposals if item.review_status == "rejected"
                ],
            }
        )
        if output_type == "reviewed_boxes":
            reviewed_payload["annotation_ids"] = [
                item.accepted_annotation_id
                for item in accepted
                if item.accepted_annotation_id is not None
            ]
        else:
            reviewed_payload["mask_annotation_ids"] = [
                item.accepted_mask_annotation_id
                for item in accepted
                if item.accepted_mask_annotation_id is not None
            ]
    elif source.data_type == "classification_predictions":
        prediction_ids = [str(value) for value in payload.get("prediction_ids", [])]
        predictions = list(
            session.scalars(
                select(ClassificationPrediction).where(
                    ClassificationPrediction.id.in_(prediction_ids)
                )
            )
        )
        pending = [item.id for item in predictions if item.status == "pending"]
        if pending:
            raise WorkflowReviewRequired(
                f"{len(pending)} classification prediction(s) still require review",
                details={
                    "node_run_id": node_run.id,
                    "pending_prediction_ids": pending,
                },
            )
        classification_accepted = [item for item in predictions if item.status == "accepted"]
        reviewed_payload.update(
            {
                "accepted_prediction_ids": [item.id for item in classification_accepted],
                "rejected_prediction_ids": [
                    item.id for item in predictions if item.status == "rejected"
                ],
                "image_label_ids": [
                    item.accepted_image_label_id
                    for item in classification_accepted
                    if item.accepted_image_label_id is not None
                ],
            }
        )
    elif source.data_type == "detection_consensus":
        reviewed_payload.update(
            {
                "detections": list(payload.get("detections", [])),
                "count": int(payload.get("count", 0) or 0),
                "consensus": True,
            }
        )
    else:
        raise ValidationError(f"Unsupported human-review artifact: {source.data_type}")

    return [
        {
            "port_id": output_port,
            "data_type": output_type,
            "payload": reviewed_payload,
        }
    ]


def _detection_review_gate(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters
    return _review_gate(
        session,
        project_id,
        inputs,
        node_type="detection_review_gate",
        input_port="proposals",
        output_port="boxes",
        output_type="reviewed_boxes",
    )


def _mask_review_gate(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters
    return _review_gate(
        session,
        project_id,
        inputs,
        node_type="mask_review_gate",
        input_port="proposals",
        output_port="masks",
        output_type="reviewed_masks",
    )


def _classification_review_gate(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, parameters
    return _review_gate(
        session,
        project_id,
        inputs,
        node_type="classification_review_gate",
        input_port="predictions",
        output_port="labels",
        output_type="reviewed_labels",
    )


def _prompt_assist_masks(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    boxes_artifact = _single_artifact(inputs, "boxes")
    model_payload = _single_payload(inputs, "model")
    model_id = str(model_payload.get("model_id") or "")
    if not model_id:
        raise ValidationError("Prompt Assist Masks requires a registered assist model")
    payload = create_prompt_assist_mask_proposals(
        session,
        settings,
        project_id=project_id,
        boxes_artifact=boxes_artifact,
        model_id=model_id,
        device=str(parameters.get("device", "auto")),
    )
    return [
        {
            "port_id": "proposals",
            "data_type": "mask_proposals",
            "payload": payload,
        }
    ]


def _relative_depth_estimation(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    image_payload = _single_payload(inputs, "images")
    model_payload = _single_payload(inputs, "model")
    if image_payload.get("project_id") != project_id:
        raise ValidationError("Relative Depth Estimation received images from another project")
    image_ids = [str(value) for value in image_payload.get("image_ids", [])]
    model_id = str(model_payload.get("model_id") or "")
    payload = create_depth_map_artifacts(
        session,
        settings,
        project_id=project_id,
        image_ids=image_ids,
        model_id=model_id,
        device=str(parameters.get("device", "auto")),
    )
    return [
        {
            "port_id": "depth_maps",
            "data_type": "relative_depth_maps",
            "payload": payload,
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


def _ecology_connected_branch_preview(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    from reefvision.schemas.connected_branch_editing import ConnectedBranchPreviewRequest
    from reefvision.services.connected_branch_preview import preview_saved_branch_addition

    runtime_keys = {"__workflow_run_id", "__workflow_node_run_id"}
    allowed = runtime_keys | {"analysis_id", "edit_id", "points"}
    if set(parameters) - allowed:
        raise ValidationError("Connected branch preview has unsupported parameters")
    project = _single_payload(inputs, "project")
    if project.get("project_id") != project_id:
        raise ValidationError("Connected branch preview requires the current project source")
    analysis_id = parameters.get("analysis_id")
    if not isinstance(analysis_id, str) or not analysis_id:
        raise ValidationError("Connected branch preview requires a saved analysis ID")
    request = ConnectedBranchPreviewRequest.model_validate(
        {"edit_id": parameters.get("edit_id"), "points": parameters.get("points")}
    )
    preview = preview_saved_branch_addition(session, settings, analysis_id, request)
    image = session.get(ImageAsset, preview.image_id)
    if image is None or image.project_id != project_id:
        raise ValidationError("Connected branch preview source belongs to another project")
    return [
        {
            "port_id": "preview",
            "data_type": "connected_branch_preview",
            "payload": {"project_id": project_id, **preview.model_dump(mode="json")},
        }
    ]


def _ecology_identity_registry_source(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    from reefvision.services.ecology_identity import EcologyIdentityService
    from reefvision.services.ecology_measurement_candidates import (
        EcologyMeasurementCandidateService,
    )

    del settings
    # The workflow executor injects these two run-trace identifiers into every
    # runtime adapter. They are not scientist-configurable node parameters.
    runtime_keys = {"__workflow_run_id", "__workflow_node_run_id"}
    if set(parameters) - runtime_keys:
        raise ValidationError("Ecological identity registry source accepts no parameters")
    project = _single_payload(inputs, "project")
    if project.get("project_id") != project_id:
        raise ValidationError("Identity registry requires the current project source")
    snapshot = EcologyIdentityService(session).registry(project_id)
    if not snapshot.identities:
        raise ValidationError("Register an organism before sourcing an identity registry")
    measurement = EcologyMeasurementCandidateService(session).candidates(
        project_id, registry=snapshot
    )
    if measurement.candidate_report is None:
        raise ValidationError("Ecological candidate report was not generated")
    return [
        {
            "port_id": "registry",
            "data_type": "ecology_identity_registry",
            "payload": snapshot.model_dump(mode="json"),
        },
        {
            "port_id": "measurement_candidates",
            "data_type": "ecology_measurement_candidates",
            "payload": measurement.model_dump(mode="json"),
        },
        {
            "port_id": "candidate_report",
            "data_type": "ecology_candidate_report",
            "payload": measurement.candidate_report.model_dump(mode="json"),
        },
    ]


def _ecology_measurement_csv_export(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    from reefvision.schemas.ecology_measurement_candidates import (
        EcologyMeasurementCandidatesResponse,
    )
    from reefvision.services.ecology_candidate_measurements_export import (
        render_ecology_measurements_csv,
    )

    del session, settings
    runtime_keys = {"__workflow_run_id", "__workflow_node_run_id"}
    if set(parameters) - runtime_keys:
        raise ValidationError("Ecological measurement CSV export accepts no parameters")
    source = EcologyMeasurementCandidatesResponse.model_validate(
        _single_payload(inputs, "candidates")
    )
    if source.project_id != project_id:
        raise ValidationError("Ecological measurement export requires current project sources")
    csv_text = render_ecology_measurements_csv(source)
    fingerprint_rechecked = source.source_fingerprint_contract is not None
    report = source.candidate_report
    if report is None:
        raise ValidationError("Ecological candidate report is missing")
    return [
        {
            "port_id": "csv",
            "data_type": "ecology_measurement_csv",
            "payload": {
                "schema_version": "ecology-measurement-export-0001",
                "project_id": project_id,
                "source_input_sha256": source.input_sha256,
                "report_sha256": report.report_sha256,
                "source_fingerprint_rechecked": fingerprint_rechecked,
                "csv_text": csv_text,
                "evidence_level": "linked_unverified",
                "review_gate": "scientist_review_required",
            },
        }
    ]


def _ecology_population_csv_export(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    from reefvision.schemas.ecology_measurement_candidates import (
        EcologyMeasurementCandidatesResponse,
    )
    from reefvision.services.ecology_population_export import render_ecology_population_csv

    del session, settings
    runtime_keys = {"__workflow_run_id", "__workflow_node_run_id"}
    if set(parameters) - runtime_keys:
        raise ValidationError("Ecological population CSV export accepts no parameters")
    source = EcologyMeasurementCandidatesResponse.model_validate(
        _single_payload(inputs, "candidates")
    )
    if source.project_id != project_id:
        raise ValidationError("Ecological population export requires current project sources")
    csv_text = render_ecology_population_csv(source)
    report = source.candidate_report
    if report is None:
        raise ValidationError("Ecological candidate report is missing")
    return [
        {
            "port_id": "csv",
            "data_type": "ecology_population_csv",
            "payload": {
                "schema_version": "ecology-population-export-0001",
                "project_id": project_id,
                "source_input_sha256": source.input_sha256,
                "report_sha256": report.report_sha256,
                "source_fingerprint_rechecked": True,
                "csv_text": csv_text,
                "evidence_level": "linked_unverified",
                "review_gate": "scientist_review_required",
            },
        }
    ]


def _ecology_longitudinal_analysis(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest

    del session, settings
    project = _single_payload(inputs, "project")
    if project.get("project_id") != project_id:
        raise ValidationError("Longitudinal analysis requires the current project source")
    request = LongitudinalAnalysisRequest.model_validate(
        {
            "observations": parameters.get("observations"),
            "experimental_unit_type": parameters.get("experimental_unit_type"),
            "expected_organism_ids_by_unit": parameters.get("expected_organism_ids_by_unit"),
            "expected_sampling_dates_by_unit": parameters.get("expected_sampling_dates_by_unit"),
        }
    )
    analysis = analyze_longitudinal(request)
    return [
        {
            "port_id": "analysis",
            "data_type": "longitudinal_analysis",
            "payload": {
                "schema_version": "longitudinal-analysis-0001",
                "project_id": project_id,
                "source_record_ids": [obs.source_record_id for obs in request.observations],
                **analysis.model_dump(mode="json"),
            },
        }
    ]


def _ecology_paired_count_comparison(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    from reefvision.schemas.model_agreement import PairedCountComparisonRequest

    del session, settings
    project = _single_payload(inputs, "project")
    if project.get("project_id") != project_id:
        raise ValidationError("Paired count comparison requires the current project source")
    request = PairedCountComparisonRequest.model_validate(
        {
            "pairs": parameters.get("pairs"),
            "reference_kind": parameters.get("reference_kind"),
            "experimental_unit_type": parameters.get("experimental_unit_type"),
        }
    )
    comparison = compare_paired_counts(request)
    return [
        {
            "port_id": "comparison",
            "data_type": "paired_count_comparison",
            "payload": {
                "schema_version": "paired-count-comparison-0001",
                "project_id": project_id,
                "reference_source_record_ids": [
                    pair.reference_source_record_id for pair in request.pairs
                ],
                "model_source_record_ids": [pair.model_source_record_id for pair in request.pairs],
                **comparison.model_dump(mode="json"),
            },
        }
    ]


def _ecology_paired_count_csv_export(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    """Recheck a saved comparison and persist an unverified CSV artifact."""
    import hashlib

    from reefvision.schemas.model_agreement import PairedCountComparisonResponse
    from reefvision.services.ecology_paired_count_export import (
        PAIRED_COUNT_CSV_SCHEMA_VERSION,
        render_paired_count_csv,
    )

    del session, settings
    runtime_keys = {"__workflow_run_id", "__workflow_node_run_id"}
    if set(parameters) - runtime_keys:
        raise ValidationError("Paired count CSV export accepts no parameters")
    payload = _single_payload(inputs, "comparison")
    if payload.get("project_id") != project_id:
        raise ValidationError("Paired count CSV export requires current project sources")
    comparison = PairedCountComparisonResponse.model_validate(payload)
    csv_text = render_paired_count_csv(comparison)
    return [
        {
            "port_id": "csv",
            "data_type": "paired_count_comparison_csv",
            "payload": {
                "schema_version": PAIRED_COUNT_CSV_SCHEMA_VERSION,
                "project_id": project_id,
                "source_input_sha256": (comparison.analysis_provenance.canonical_input_sha256),
                "source_record_ids": comparison.analysis_provenance.source_record_ids,
                "algorithm_version": comparison.analysis_provenance.algorithm_version,
                "csv_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
                "csv_text": csv_text,
                "evidence_level": "caller_supplied_unverified",
                "review_status": "requires_source_verification",
                "independent_unit_inference_allowed": False,
            },
        }
    ]


_ADAPTERS = {
    "segmentation_inference": _segmentation_inference,
    "classification_inference": _classification_inference,
    "vlm_detection": _vlm_detection,
    "detection_review_gate": _detection_review_gate,
    "mask_review_gate": _mask_review_gate,
    "classification_review_gate": _classification_review_gate,
    "prompt_assist_masks": _prompt_assist_masks,
    "relative_depth_estimation": _relative_depth_estimation,
    "mask_measurements": _mask_measurements,
    "video_tracking": _video_tracking,
    "ecology_longitudinal_analysis": _ecology_longitudinal_analysis,
    "ecology_identity_registry_source": _ecology_identity_registry_source,
    "ecology_connected_branch_preview": _ecology_connected_branch_preview,
    "ecology_measurement_csv_export": _ecology_measurement_csv_export,
    "ecology_population_csv_export": _ecology_population_csv_export,
    "ecology_paired_count_comparison": _ecology_paired_count_comparison,
    "ecology_paired_count_csv_export": _ecology_paired_count_csv_export,
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
