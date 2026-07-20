"""Restart-safe execution of persisted, validated workflow graphs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ClassificationPrediction,
    DepthMap,
    ImageAsset,
    ImageEmbedding,
    Job,
    MaskAnnotation,
    PredictionProposal,
    Project,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
    WorkflowRevision,
    WorkflowRun,
)
from reefvision.jobs.classification_inference import process_classification_inference_job
from reefvision.jobs.depth import process_depth_map_job
from reefvision.jobs.image_embeddings import process_image_embedding_job
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.schemas.image_embeddings import EmbeddingDiversitySelectionRequest
from reefvision.schemas.workflows import WorkflowValidationRequest, WorkflowValidationResponse
from reefvision.services.image_embeddings import ImageEmbeddingService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

ArtifactOutput = tuple[str, dict[str, Any]] | tuple[str, dict[str, Any], str, int]
ArtifactOutputs = dict[str, ArtifactOutput]


def _artifact_payload(artifact: WorkflowArtifact) -> dict[str, Any]:
    return dict(artifact.payload_json or {})


def _list_values(payloads: list[dict[str, Any]], *keys: str) -> list[str]:
    values: list[str] = []
    for payload in payloads:
        for key in keys:
            raw = payload.get(key)
            if isinstance(raw, list):
                values.extend(str(item) for item in raw)
    return list(dict.fromkeys(values))


def _cache_key(
    node_type: str,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> str:
    return canonical_json_sha256(
        {
            "node_type": node_type,
            "configuration": configuration,
            "inputs": [
                {
                    "artifact_type": artifact.artifact_type,
                    "checksum": artifact.checksum,
                    "port_name": artifact.port_name,
                }
                for artifact in sorted(inputs, key=lambda item: (item.node_id, item.port_name))
            ],
        }
    )


def _save_artifact(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    port_name: str,
    artifact_type: str,
    payload: dict[str, Any],
    managed_path: str | None = None,
    size_bytes: int | None = None,
) -> WorkflowArtifact:
    checksum = canonical_json_sha256(payload)
    artifact = WorkflowArtifact(
        workflow_run_id=run.id,
        node_id=node_id,
        port_name=port_name,
        artifact_type=artifact_type,
        checksum=checksum,
        payload_json=payload,
        managed_path=managed_path,
        size_bytes=size_bytes,
    )
    session.add(artifact)
    session.flush()
    return artifact


def _cached_outputs(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    cache_key: str,
) -> list[WorkflowArtifact]:
    candidates = list(
        session.scalars(
            select(WorkflowArtifact)
            .join(WorkflowRun, WorkflowRun.id == WorkflowArtifact.workflow_run_id)
            .where(
                WorkflowRun.project_id == run.project_id,
                WorkflowArtifact.node_id == node_id,
                WorkflowRun.status == "succeeded",
            )
            .order_by(WorkflowArtifact.created_at.desc())
        )
    )
    return [
        artifact
        for artifact in candidates
        if _artifact_payload(artifact).get("_cache_key") == cache_key
    ]


def _copy_cached_outputs(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    cached: list[WorkflowArtifact],
) -> list[WorkflowArtifact]:
    return [
        _save_artifact(
            session,
            run=run,
            node_id=node_id,
            port_name=artifact.port_name,
            artifact_type=artifact.artifact_type,
            payload={**_artifact_payload(artifact), "_reused_from_artifact_id": artifact.id},
            managed_path=artifact.managed_path,
            size_bytes=artifact.size_bytes,
        )
        for artifact in cached
    ]


def _child_job(
    session: Session,
    *,
    project_id: str,
    job_type: str,
    request_json: dict[str, Any],
    progress_total: int = 1,
) -> Job:
    child = Job(
        project_id=project_id,
        job_type=job_type,
        status="queued",
        progress_total=max(progress_total, 1),
        request_json=request_json,
    )
    session.add(child)
    session.commit()
    session.refresh(child)
    return child


def _require_child_success(factory: sessionmaker[Session], child_id: str) -> dict[str, Any]:
    with factory() as session:
        child = session.get(Job, child_id)
        if child is None:
            raise RuntimeError("Workflow child job disappeared")
        if child.status not in {"succeeded", "completed"}:
            raise RuntimeError(child.error_message or f"Child job ended as {child.status}")
        return dict(child.result_json or {})


def _image_input(
    session: Session,
    run: WorkflowRun,
    configuration: dict[str, Any],
) -> ArtifactOutputs:
    configured = configuration.get("image_ids")
    requested = (
        [str(item) for item in configured]
        if isinstance(configured, list)
        else [str(item) for item in run.input_json.get("image_ids", [])]
    )
    query = select(ImageAsset).where(ImageAsset.project_id == run.project_id)
    if requested:
        query = query.where(ImageAsset.id.in_(requested))
    images = list(session.scalars(query.order_by(ImageAsset.created_at, ImageAsset.id)))
    if requested and len(images) != len(set(requested)):
        raise RuntimeError("One or more workflow input images are missing")
    return {
        "images": (
            "images",
            {
                "image_ids": [image.id for image in images],
                "image_count": len(images),
                "checksums": {image.id: image.sha256 for image in images},
            },
        )
    }


def _video_input(
    session: Session,
    run: WorkflowRun,
    configuration: dict[str, Any],
) -> ArtifactOutputs:
    configured = configuration.get("video_ids")
    requested = (
        [str(item) for item in configured]
        if isinstance(configured, list)
        else [str(item) for item in run.input_json.get("video_ids", [])]
    )
    query = select(VideoAsset).where(VideoAsset.project_id == run.project_id)
    if requested:
        query = query.where(VideoAsset.id.in_(requested))
    videos = list(session.scalars(query.order_by(VideoAsset.created_at, VideoAsset.id)))
    if requested and len(videos) != len(set(requested)):
        raise RuntimeError("One or more workflow input videos are missing")
    return {
        "video": (
            "video",
            {
                "video_ids": [video.id for video in videos],
                "video_count": len(videos),
                "checksums": {video.id: video.sha256 for video in videos},
            },
        )
    }


def _depth_estimation(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    image_ids = _list_values([_artifact_payload(item) for item in inputs], "image_ids")
    provider_id = str(configuration.get("provider_id", "depth_anything_v2_relative"))
    model_id = str(configuration.get("model_id", "depth-anything/Depth-Anything-V2-Small-hf"))
    depth_kind = str(configuration.get("depth_kind", "relative"))
    depth_map_ids: list[str] = []
    child_job_ids: list[str] = []
    for image_id in image_ids:
        with factory() as session:
            existing = session.scalar(
                select(DepthMap).where(
                    DepthMap.image_id == image_id,
                    DepthMap.provider_id == provider_id,
                    DepthMap.model_id == model_id,
                    DepthMap.depth_kind == depth_kind,
                )
            )
            if existing is not None and not bool(configuration.get("replace_existing", False)):
                depth_map_ids.append(existing.id)
                continue
            depth_map_id = str(uuid4())
            child = _child_job(
                session,
                project_id=run.project_id,
                job_type="depth_map",
                request_json={
                    "depth_map_id": depth_map_id,
                    "image_id": image_id,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "device": str(configuration.get("device", "auto")),
                    "local_files_only": bool(configuration.get("local_files_only", True)),
                    "depth_kind": depth_kind,
                    "unit": configuration.get("unit"),
                    "maximum_metric_depth": configuration.get("maximum_metric_depth"),
                    "camera_intrinsics": configuration.get("camera_intrinsics"),
                    "parent_workflow_run_id": run.id,
                },
            )
        child_job_ids.append(child.id)
        process_depth_map_job(settings, factory, child.id)
        _require_child_success(factory, child.id)
        depth_map_ids.append(depth_map_id)
    return {
        "depth_maps": (
            "depth_maps",
            {
                "image_ids": image_ids,
                "depth_map_ids": depth_map_ids,
                "provider_id": provider_id,
                "model_id": model_id,
                "depth_kind": depth_kind,
                "child_job_ids": child_job_ids,
            },
        )
    }


def _embedding_generation(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    image_ids = _list_values([_artifact_payload(item) for item in inputs], "image_ids")
    model_id = str(configuration.get("model_id", "reefvision-color-texture-v1"))
    with factory() as session:
        child = _child_job(
            session,
            project_id=run.project_id,
            job_type="image_embeddings",
            progress_total=len(image_ids),
            request_json={
                "project_id": run.project_id,
                "provider_id": str(configuration.get("provider_id", "color_texture_v1")),
                "model_id": model_id,
                "device": str(configuration.get("device", "auto")),
                "local_files_only": bool(configuration.get("local_files_only", True)),
                "replace_existing": bool(configuration.get("replace_existing", False)),
                "resolved_image_ids": image_ids,
                "parent_workflow_run_id": run.id,
            },
        )
    process_image_embedding_job(settings, factory, child.id)
    child_result = _require_child_success(factory, child.id)
    with factory() as session:
        embeddings = list(
            session.scalars(
                select(ImageEmbedding).where(
                    ImageEmbedding.project_id == run.project_id,
                    ImageEmbedding.image_id.in_(image_ids),
                    ImageEmbedding.embedding_model_id == model_id,
                )
            )
        )
    return {
        "embeddings": (
            "embeddings",
            {
                "image_ids": image_ids,
                "embedding_ids": [item.id for item in embeddings],
                "embedding_model_id": model_id,
                "dimension": embeddings[0].dimension if embeddings else None,
                "child_job_id": child.id,
                "child_result": child_result,
            },
        )
    }


def _model_inference(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    node_type: str,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    image_ids = _list_values([_artifact_payload(item) for item in inputs], "image_ids")
    model_id = str(configuration.get("model_id", ""))
    if not model_id:
        raise RuntimeError(f"{node_type} nodes require model_id")
    with factory() as session:
        child = _child_job(
            session,
            project_id=run.project_id,
            job_type="inference",
            progress_total=len(image_ids),
            request_json={
                "model_id": model_id,
                "image_ids": image_ids,
                "device": str(configuration.get("device", "auto")),
                "confidence": float(configuration.get("confidence", 0.25)),
                "iou_threshold": float(configuration.get("iou_threshold", 0.45)),
                "max_det": int(configuration.get("max_det", 1000)),
                "batch_size": int(configuration.get("batch_size", 1)),
                "inference_width": configuration.get("inference_width"),
                "inference_height": configuration.get("inference_height"),
                "save_txt": bool(configuration.get("save_txt", False)),
                "save_conf": bool(configuration.get("save_conf", False)),
                "save_crop": bool(configuration.get("save_crop", False)),
                "source_kind": "workflow",
                "parent_workflow_run_id": run.id,
            },
        )
    process_inference_job(settings, factory, child.id)
    child_result = _require_child_success(factory, child.id)
    with factory() as session:
        predictions = list(
            session.scalars(
                select(PredictionProposal).where(PredictionProposal.inference_job_id == child.id)
            )
        )
    output_port = "detections" if node_type == "detector" else "masks"
    return {
        output_port: (
            output_port,
            {
                "image_ids": image_ids,
                "prediction_ids": [item.id for item in predictions],
                "model_id": model_id,
                "child_job_id": child.id,
                "child_result": child_result,
            },
        )
    }


def _classification(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    payloads = [_artifact_payload(item) for item in inputs]
    image_ids = _list_values(payloads, "image_ids")
    annotation_ids = _list_values(payloads, "annotation_ids")
    model_id = str(configuration.get("model_id", ""))
    if not model_id:
        raise RuntimeError("Classifier nodes require model_id")
    if not annotation_ids:
        with factory() as session:
            annotation_ids = list(
                session.scalars(
                    select(Annotation.id).where(
                        Annotation.image_id.in_(image_ids),
                        Annotation.deleted_at.is_(None),
                    )
                )
            )
    with factory() as session:
        child = _child_job(
            session,
            project_id=run.project_id,
            job_type="classification_inference",
            progress_total=len(annotation_ids),
            request_json={
                "model_id": model_id,
                "image_ids": image_ids,
                "annotation_ids": annotation_ids,
                "device": str(configuration.get("device", "auto")),
                "confidence_threshold": float(configuration.get("confidence_threshold", 0.0)),
                "batch_size": int(configuration.get("batch_size", 32)),
                "label_set": configuration.get("label_set"),
                "parent_workflow_run_id": run.id,
            },
        )
    process_classification_inference_job(settings, factory, child.id)
    child_result = _require_child_success(factory, child.id)
    with factory() as session:
        predictions = list(
            session.scalars(
                select(ClassificationPrediction).where(
                    ClassificationPrediction.inference_job_id == child.id
                )
            )
        )
    return {
        "classifications": (
            "classifications",
            {
                "image_ids": image_ids,
                "annotation_ids": annotation_ids,
                "classification_prediction_ids": [item.id for item in predictions],
                "model_id": model_id,
                "child_job_id": child.id,
                "child_result": child_result,
            },
        )
    }


def _tracker(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    video_ids = _list_values([_artifact_payload(item) for item in inputs], "video_ids")
    model_id = str(configuration.get("model_id", ""))
    if not model_id:
        raise RuntimeError("Tracker nodes require detector model_id")
    track_ids: list[str] = []
    child_job_ids: list[str] = []
    for video_id in video_ids:
        with factory() as session:
            child = _child_job(
                session,
                project_id=run.project_id,
                job_type="video_track",
                request_json={
                    "video_id": video_id,
                    "model_id": model_id,
                    "tracker": str(configuration.get("tracker", "bytetrack")),
                    "every_n_frames": int(configuration.get("every_n_frames", 1)),
                    "replace_generated_tracks": bool(
                        configuration.get("replace_generated_tracks", True)
                    ),
                    "confidence_threshold": float(configuration.get("confidence_threshold", 0.25)),
                    "iou_threshold": float(configuration.get("iou_threshold", 0.45)),
                    "device": str(configuration.get("device", "auto")),
                    "parent_workflow_run_id": run.id,
                },
            )
        child_job_ids.append(child.id)
        process_video_tracking_job(settings, factory, child.id)
        _require_child_success(factory, child.id)
        with factory() as session:
            tracks = list(
                session.scalars(
                    select(VideoTrack).where(
                        VideoTrack.video_id == video_id,
                        VideoTrack.status == "generated",
                    )
                )
            )
            track_ids.extend(item.id for item in tracks)
    return {
        "tracks": (
            "tracks",
            {
                "video_ids": video_ids,
                "track_ids": track_ids,
                "model_id": model_id,
                "child_job_ids": child_job_ids,
            },
        )
    }


def _measurement_snapshot(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    payloads = [_artifact_payload(item) for item in inputs]
    image_ids = _list_values(payloads, "image_ids")
    configured = configuration.get("mask_annotation_ids")
    mask_ids = [str(value) for value in configured] if isinstance(configured, list) else []
    with factory() as session:
        query = (
            select(MaskAnnotation)
            .join(
                ImageAsset,
                ImageAsset.id == MaskAnnotation.image_id,
            )
            .where(
                ImageAsset.project_id == run.project_id,
                MaskAnnotation.deleted_at.is_(None),
            )
        )
        if mask_ids:
            query = query.where(MaskAnnotation.id.in_(mask_ids))
        elif image_ids:
            query = query.where(MaskAnnotation.image_id.in_(image_ids))
        masks = list(session.scalars(query.order_by(MaskAnnotation.image_id, MaskAnnotation.id)))
    measurements = [
        {
            "mask_annotation_id": mask.id,
            "image_id": mask.image_id,
            "label_class_id": mask.label_class_id,
            "geometry_kind": mask.geometry_kind,
            "area_pixels": mask.area_pixels,
            "bounds": [mask.x_min, mask.y_min, mask.x_max, mask.y_max],
            "measurement": dict(mask.measurement_json or {}),
        }
        for mask in masks
    ]
    return {
        "measurements": (
            "measurements",
            {
                "image_ids": list(dict.fromkeys(mask.image_id for mask in masks)),
                "mask_annotation_ids": [mask.id for mask in masks],
                "measurement_count": len(measurements),
                "measurements": measurements,
            },
        )
    }


def _behavior_snapshot(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    video_ids = _list_values([_artifact_payload(item) for item in inputs], "video_ids")
    with factory() as session:
        tracks = list(
            session.scalars(
                select(VideoTrack)
                .join(VideoAsset, VideoAsset.id == VideoTrack.video_id)
                .where(
                    VideoAsset.project_id == run.project_id,
                    VideoTrack.video_id.in_(video_ids),
                )
            )
        )
    summaries = [
        {
            "track_id": track.id,
            "video_id": track.video_id,
            "track_number": track.track_number,
            "keyframe_count": len(track.keyframes_json or []),
            "metadata": dict(track.metadata_json or {}),
        }
        for track in tracks
    ]
    return {
        "measurements": (
            "measurements",
            {
                "video_ids": video_ids,
                "track_ids": [track.id for track in tracks],
                "track_summary_count": len(summaries),
                "track_summaries": summaries,
            },
        )
    }


def _active_learning(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    payloads = [_artifact_payload(item) for item in inputs]
    image_ids = _list_values(payloads, "image_ids")
    embedding_model_id = str(configuration.get("embedding_model_id", ""))
    if not embedding_model_id:
        for payload in payloads:
            value = payload.get("embedding_model_id")
            if isinstance(value, str):
                embedding_model_id = value
                break
    if not embedding_model_id:
        raise RuntimeError("Active-learning nodes require embedding_model_id")
    request = EmbeddingDiversitySelectionRequest(
        embedding_model_id=embedding_model_id,
        candidate_image_ids=image_ids,
        maximum_items=int(configuration.get("maximum_items", 100)),
        diversity_weight=float(configuration.get("diversity_weight", 0.7)),
        base_scores={
            str(key): float(value)
            for key, value in (
                configuration.get("base_scores", {}).items()
                if isinstance(configuration.get("base_scores"), dict)
                else []
            )
        },
        maximum_items_per_group=(
            int(configuration["maximum_items_per_group"])
            if configuration.get("maximum_items_per_group") is not None
            else None
        ),
    )
    with factory() as session:
        response = ImageEmbeddingService(session).select_diverse_candidates(
            run.project_id,
            request,
        )
    return {
        "review_batch": (
            "review_batch",
            response.model_dump(mode="json"),
        )
    }


def _filter_artifact(
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    if not inputs:
        raise RuntimeError("Filter nodes require an input artifact")
    source = inputs[0]
    payload = _artifact_payload(source)
    limit = int(configuration.get("limit", 0))
    include_ids = {
        str(value)
        for value in configuration.get("include_ids", [])
        if isinstance(configuration.get("include_ids"), list)
    }
    filtered: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            items = [item for item in value if not include_ids or str(item) in include_ids]
            filtered[key] = items[:limit] if limit > 0 else items
        else:
            filtered[key] = value
    return {"artifact": (source.artifact_type, filtered)}


def _export_json(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    node_id: str,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> ArtifactOutputs:
    with factory() as session:
        project = session.get(Project, run.project_id)
        if project is None:
            raise RuntimeError("Workflow project is missing")
        relative = f"{project.storage_root}/workflows/{run.id}/{node_id}.json"
        path = resolve_managed_project_path(settings, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "workflow_run_id": run.id,
        "node_id": node_id,
        "format": str(configuration.get("format", "json")),
        "artifacts": [
            {
                "artifact_type": artifact.artifact_type,
                "port_name": artifact.port_name,
                "checksum": artifact.checksum,
                "payload": _artifact_payload(artifact),
            }
            for artifact in inputs
        ],
    }
    encoded = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid4().hex[:8]}.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    payload = {
        "workflow_run_id": run.id,
        "managed_path": relative,
        "format": "json",
        "source_artifact_count": len(inputs),
    }
    return {"archive": ("export_archive", payload, relative, len(encoded))}


def _node_inputs(
    session: Session,
    run: WorkflowRun,
    workflow: WorkflowValidationRequest,
    node_id: str,
) -> list[WorkflowArtifact]:
    incoming = [edge for edge in workflow.edges if edge.target_node_id == node_id]
    artifacts: list[WorkflowArtifact] = []
    for edge in incoming:
        artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run.id,
                WorkflowArtifact.node_id == edge.source_node_id,
                WorkflowArtifact.port_name == edge.source_port,
            )
        )
        if artifact is None:
            raise RuntimeError(
                f"Input artifact {edge.source_node_id}.{edge.source_port} is missing"
            )
        artifacts.append(artifact)
    return artifacts


def process_workflow_run_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "workflow_run" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("workflow_run_id", ""))
        run = session.get(WorkflowRun, run_id)
        revision = (
            session.get(WorkflowRevision, run.workflow_revision_id) if run is not None else None
        )
        if run is None or revision is None:
            job.status = "failed"
            job.error_message = "Workflow run references missing persistence records"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        workflow = WorkflowValidationRequest.model_validate(revision.workflow_json)
        validation = WorkflowValidationResponse.model_validate(revision.validation_json)
        run.status = "running"
        run.stage = "executing"
        run.started_at = run.started_at or datetime.now(UTC)
        job.status = "running"
        job.started_at = job.started_at or datetime.now(UTC)
        session.commit()

    try:
        for index, node_id in enumerate(validation.topological_order):
            with factory() as session:
                run = session.get(WorkflowRun, run_id)
                job = session.get(Job, job_id)
                if run is None or job is None:
                    raise RuntimeError("Workflow run disappeared during execution")
                if job.status == "cancel_requested" or run.status == "cancel_requested":
                    run.status = "cancelled"
                    run.stage = "cancelled"
                    run.completed_at = datetime.now(UTC)
                    job.status = "cancelled"
                    job.completed_at = datetime.now(UTC)
                    session.commit()
                    return True
                node = next(item for item in workflow.nodes if item.id == node_id)
                existing = list(
                    session.scalars(
                        select(WorkflowArtifact).where(
                            WorkflowArtifact.workflow_run_id == run.id,
                            WorkflowArtifact.node_id == node.id,
                        )
                    )
                )
                if existing:
                    state = dict(run.node_state_json or {})
                    state[node.id] = {
                        "status": "succeeded",
                        "artifact_ids": [item.id for item in existing],
                        "resumed": True,
                    }
                    run.node_state_json = state
                    job.progress_current = index + 1
                    session.commit()
                    continue
                inputs = _node_inputs(session, run, workflow, node.id)
                cache_key = _cache_key(node.node_type, node.configuration, inputs)
                use_cache = bool(run.result_json.get("use_cache", True))
                if use_cache:
                    cached = _cached_outputs(
                        session,
                        run=run,
                        node_id=node.id,
                        cache_key=cache_key,
                    )
                    if cached:
                        cached_artifacts = _copy_cached_outputs(
                            session,
                            run=run,
                            node_id=node.id,
                            cached=cached,
                        )
                        state = dict(run.node_state_json or {})
                        state[node.id] = {
                            "status": "succeeded",
                            "artifact_ids": [item.id for item in cached_artifacts],
                            "cache_hit": True,
                        }
                        run.node_state_json = state
                        job.progress_current = index + 1
                        session.commit()
                        continue
                run.current_node_id = node.id
                run.stage = f"node:{node.id}"
                state = dict(run.node_state_json or {})
                state[node.id] = {"status": "running", "started_at": datetime.now(UTC).isoformat()}
                run.node_state_json = state
                job.result_json = {"stage": run.stage, "node_id": node.id}
                session.commit()
                run_snapshot = run

            if node.node_type == "image_input":
                with factory() as session:
                    run_record = session.get(WorkflowRun, run_id)
                    assert run_record is not None
                    outputs = _image_input(session, run_record, node.configuration)
            elif node.node_type == "video_input":
                with factory() as session:
                    run_record = session.get(WorkflowRun, run_id)
                    assert run_record is not None
                    outputs = _video_input(session, run_record, node.configuration)
            elif node.node_type == "depth_estimation":
                outputs = _depth_estimation(
                    settings,
                    factory,
                    run_snapshot,
                    node.configuration,
                    inputs,
                )
            elif node.node_type == "embedding_generation":
                outputs = _embedding_generation(
                    settings,
                    factory,
                    run_snapshot,
                    node.configuration,
                    inputs,
                )
            elif node.node_type in {"detector", "segmenter"}:
                outputs = _model_inference(
                    settings,
                    factory,
                    run_snapshot,
                    node.node_type,
                    node.configuration,
                    inputs,
                )
            elif node.node_type == "classifier":
                outputs = _classification(
                    settings,
                    factory,
                    run_snapshot,
                    node.configuration,
                    inputs,
                )
            elif node.node_type == "tracker":
                outputs = _tracker(
                    settings,
                    factory,
                    run_snapshot,
                    node.configuration,
                    inputs,
                )
            elif node.node_type == "measurement":
                outputs = _measurement_snapshot(
                    factory,
                    run_snapshot,
                    node.configuration,
                    inputs,
                )
            elif node.node_type == "behavior_analysis":
                outputs = _behavior_snapshot(factory, run_snapshot, inputs)
            elif node.node_type == "active_learning":
                outputs = _active_learning(
                    factory,
                    run_snapshot,
                    node.configuration,
                    inputs,
                )
            elif node.node_type == "filter":
                outputs = _filter_artifact(node.configuration, inputs)
            elif node.node_type == "export":
                outputs = _export_json(
                    settings,
                    factory,
                    run_snapshot,
                    node.id,
                    node.configuration,
                    inputs,
                )
            else:
                raise RuntimeError(f"No execution handler exists for {node.node_type}")

            with factory() as session:
                run = session.get(WorkflowRun, run_id)
                job = session.get(Job, job_id)
                if run is None or job is None:
                    raise RuntimeError("Workflow run disappeared while saving artifacts")
                saved_artifacts: list[WorkflowArtifact] = []
                for port_name, output in outputs.items():
                    artifact_type = output[0]
                    payload = {**output[1], "_cache_key": cache_key}
                    managed_path = output[2] if len(output) > 2 else None
                    size_bytes = output[3] if len(output) > 3 else None
                    saved_artifacts.append(
                        _save_artifact(
                            session,
                            run=run,
                            node_id=node.id,
                            port_name=port_name,
                            artifact_type=artifact_type,
                            payload=payload,
                            managed_path=managed_path,
                            size_bytes=size_bytes,
                        )
                    )
                state = dict(run.node_state_json or {})
                state[node.id] = {
                    "status": "succeeded",
                    "artifact_ids": [item.id for item in saved_artifacts],
                    "completed_at": datetime.now(UTC).isoformat(),
                    "cache_hit": False,
                }
                run.node_state_json = state
                job.progress_current = index + 1
                session.commit()

        with factory() as session:
            run = session.get(WorkflowRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                return False
            artifacts = list(
                session.scalars(
                    select(WorkflowArtifact).where(WorkflowArtifact.workflow_run_id == run.id)
                )
            )
            run.status = "succeeded"
            run.stage = "completed"
            run.current_node_id = None
            run.result_json = {
                **dict(run.result_json or {}),
                "artifact_count": len(artifacts),
                "artifact_ids": [item.id for item in artifacts],
            }
            run.completed_at = datetime.now(UTC)
            job.status = "succeeded"
            job.progress_current = max(job.progress_total, len(validation.topological_order))
            job.result_json = {
                "stage": "completed",
                "workflow_run_id": run.id,
                "artifact_count": len(artifacts),
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            run = session.get(WorkflowRun, run_id)
            job = session.get(Job, job_id)
            if run is not None:
                state = dict(run.node_state_json or {})
                if run.current_node_id:
                    state[run.current_node_id] = {
                        "status": "failed",
                        "error": str(exc),
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                run.node_state_json = state
                run.status = "failed"
                run.stage = "failed"
                run.error_message = str(exc)
                run.completed_at = datetime.now(UTC)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
            session.commit()
        return False
