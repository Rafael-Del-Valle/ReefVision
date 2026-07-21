"""Background detection, instance, and semantic segmentation inference."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, PredictionProposal, Project
from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import detection_provider_for_name
from reefvision.ml.providers import DetectionProvider, DetectionSettings
from reefvision.ml.segmentation import (
    SegmentationProvider,
    segmentation_provider_for_name,
)
from reefvision.ml.semantic_segmentation import (
    SEMANTIC_SEGMENTATION_TASK,
    semantic_provider_for_name,
)
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
from reefvision.storage.masks import (
    remove_prediction_mask_png,
    write_prediction_mask_png,
)
from reefvision.storage.projects import resolve_managed_project_path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _model(session: Session, model_id: str) -> ModelRegistration:
    model = ModelRepository(session).get(model_id)
    if model is None:
        raise ValidationError("The inference job references a missing model")
    return model


def _mapped_label_class_id(
    class_map_json: dict[str, Any],
    label: str,
) -> str | None:
    mapping = class_map_json.get("mapping", {})
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(label)
    return str(value) if value else None


def _model_source_provenance(model_metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_training_run_id",
        "source_dataset_version_id",
        "source_dataset_manifest_sha256",
        "source_split_manifest_sha256",
        "source_catalog_model_id",
        "source_resolved_model_asset_id",
        "source_resolved_model_checksum",
        "source_result_checkpoint_path",
    )
    return {key: model_metadata[key] for key in keys if model_metadata.get(key) is not None}


def _semantic_proposals(
    settings: Settings,
    *,
    project: Project,
    image_id: str,
    image_width: int,
    image_height: int,
    indexed_path: Path,
    model_id: str,
    model_checksum: str,
    model_provider_name: str,
    model_provider_version: str,
    model_class_map: dict[str, Any],
    model_metadata: dict[str, Any],
    job_id: str,
    device: str,
    uncommitted_mask_paths: dict[str, str],
) -> list[PredictionProposal]:
    classes = model_metadata.get("classes")
    if not isinstance(classes, list):
        raise ValidationError("Semantic model class metadata is missing")
    try:
        with Image.open(indexed_path) as source:
            source.load()
            indexed = source.convert("L")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Semantic inference output is not a readable PNG") from exc
    if indexed.size != (image_width, image_height):
        raise ValidationError("Semantic inference output dimensions do not match the image")

    proposals: list[PredictionProposal] = []
    for raw in classes:
        if not isinstance(raw, dict):
            continue
        pixel_value = int(raw["pixel_value"])
        class_index = int(raw["class_index"])
        label = str(raw["class_name"])
        binary = indexed.point(lambda value, expected=pixel_value: 255 if value == expected else 0)
        bounds = binary.getbbox()
        if bounds is None:
            continue
        histogram = binary.histogram()
        area_pixels = int(sum(histogram[1:]))
        if area_pixels <= 0:
            continue
        proposal_id = str(uuid4())
        encoded = BytesIO()
        binary.save(encoded, format="PNG", optimize=True)
        stored = write_prediction_mask_png(
            settings,
            project_storage_root=project.storage_root,
            proposal_id=proposal_id,
            png_bytes=encoded.getvalue(),
            expected_width=image_width,
            expected_height=image_height,
        )
        uncommitted_mask_paths[stored.relative_path] = proposal_id
        x_min, y_min, x_max, y_max = bounds
        proposals.append(
            PredictionProposal(
                id=proposal_id,
                project_id=project.id,
                image_id=image_id,
                model_id=model_id,
                inference_job_id=job_id,
                model_checksum=model_checksum,
                label_class_id=_mapped_label_class_id(model_class_map, label),
                predicted_label=label,
                predicted_index=class_index,
                confidence=1.0,
                geometry_kind="raster_mask",
                polygon_json=None,
                mask_path=stored.relative_path,
                mask_content_sha256=stored.content_sha256,
                x_min=float(x_min),
                y_min=float(y_min),
                x_max=float(x_max),
                y_max=float(y_max),
                review_status="pending",
                inference_settings_json={
                    "device": device,
                    "task": SEMANTIC_SEGMENTATION_TASK,
                    "confidence_kind": "hard_label",
                },
                provenance_json={
                    "provider_name": model_provider_name,
                    "provider_version": model_provider_version,
                    "model_task": SEMANTIC_SEGMENTATION_TASK,
                    "proposal_geometry": "raster_mask",
                    "pixel_value": pixel_value,
                    "area_pixels": area_pixels,
                    **_model_source_provenance(model_metadata),
                },
            )
        )
    return proposals


def process_inference_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "inference" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = _utc_now()
        job.error_message = None
        session.commit()
        request = dict(job.request_json)
        model = _model(session, str(request["model_id"]))
        model_path = resolve_managed_project_path(settings, model.managed_path)
        image_ids = [str(image_id) for image_id in request["image_ids"]]
        inference_settings = DetectionSettings(
            confidence_threshold=float(request["confidence_threshold"]),
            iou_threshold=float(request["iou_threshold"]),
            device=str(request.get("device", "auto")),
        )
        model_task = str(request.get("model_task") or model.task or "detect")
        provider_name = model.provider_name
        provider_version = model.provider_version
        model_id = model.id
        model_checksum = model.sha256
        class_map = dict(model.class_map_json or {})
        model_metadata = dict(model.metadata_json or {})
        project_id = model.project_id

    provider: DetectionProvider | SegmentationProvider | None = None
    semantic_provider = None
    if model_task == "segment":
        provider = segmentation_provider_for_name(provider_name)
    elif model_task == "detect":
        provider = detection_provider_for_name(provider_name)
    elif model_task == SEMANTIC_SEGMENTATION_TASK:
        semantic_provider = semantic_provider_for_name(provider_name)
    else:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = f"Unsupported inference model task: {model_task}"
                job.completed_at = _utc_now()
                session.commit()
        return False

    uncommitted_mask_paths: dict[str, str] = {}
    project_storage_root: str | None = None
    try:
        if provider is not None:
            provider.load_model(model_path, inference_settings.device)
        for index, image_id in enumerate(image_ids, start=1):
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.completed_at = _utc_now()
                    session.commit()
                    return True
                image = ImageRepository(session).get(image_id)
                project = session.get(Project, project_id)
                if image is None or project is None:
                    raise ValidationError("The inference job references a missing image or project")
                project_storage_root = project.storage_root
                image_path = resolve_managed_project_path(settings, image.managed_path)

                if semantic_provider is not None:
                    indexed_path = semantic_provider.predict(
                        model_path,
                        image_path,
                        device=inference_settings.device,
                    )
                    try:
                        proposals = _semantic_proposals(
                            settings,
                            project=project,
                            image_id=image.id,
                            image_width=image.width_px,
                            image_height=image.height_px,
                            indexed_path=indexed_path,
                            model_id=model_id,
                            model_checksum=model_checksum,
                            model_provider_name=provider_name,
                            model_provider_version=provider_version,
                            model_class_map=class_map,
                            model_metadata=model_metadata,
                            job_id=job_id,
                            device=inference_settings.device,
                            uncommitted_mask_paths=uncommitted_mask_paths,
                        )
                    finally:
                        indexed_path.unlink(missing_ok=True)
                else:
                    if provider is None:
                        raise RuntimeError("Inference provider is unavailable")
                    predictions = provider.predict(image_path, inference_settings)
                    proposals = []
                    for prediction in predictions:
                        polygon = getattr(prediction, "polygon", None)
                        mask_png_bytes = getattr(prediction, "mask_png_bytes", None)
                        proposal_id = str(uuid4())
                        geometry_kind = "bounding_box"
                        mask_path: str | None = None
                        mask_content_sha256: str | None = None
                        raster_metadata: dict[str, Any] = {}
                        if model_task == "segment":
                            if polygon is not None:
                                geometry_kind = "polygon_mask"
                            elif isinstance(mask_png_bytes, bytes):
                                stored = write_prediction_mask_png(
                                    settings,
                                    project_storage_root=project.storage_root,
                                    proposal_id=proposal_id,
                                    png_bytes=mask_png_bytes,
                                    expected_width=image.width_px,
                                    expected_height=image.height_px,
                                )
                                uncommitted_mask_paths[stored.relative_path] = proposal_id
                                geometry_kind = "raster_mask"
                                mask_path = stored.relative_path
                                mask_content_sha256 = stored.content_sha256
                                raster_metadata = {
                                    "area_pixels": stored.area_pixels,
                                    "raster_bounds": {
                                        "x_min": stored.x_min,
                                        "y_min": stored.y_min,
                                        "x_max": stored.x_max,
                                        "y_max": stored.y_max,
                                    },
                                }
                            else:
                                raise ValidationError(
                                    "Segmentation inference returned an instance without "
                                    "reviewable polygon or raster-mask geometry"
                                )
                        proposals.append(
                            PredictionProposal(
                                id=proposal_id,
                                project_id=image.project_id,
                                image_id=image.id,
                                model_id=model_id,
                                inference_job_id=job_id,
                                model_checksum=model_checksum,
                                label_class_id=_mapped_label_class_id(
                                    class_map,
                                    prediction.label,
                                ),
                                predicted_label=prediction.label,
                                predicted_index=prediction.class_index,
                                confidence=prediction.confidence,
                                geometry_kind=geometry_kind,
                                polygon_json=polygon,
                                mask_path=mask_path,
                                mask_content_sha256=mask_content_sha256,
                                x_min=prediction.box.x_min,
                                y_min=prediction.box.y_min,
                                x_max=prediction.box.x_max,
                                y_max=prediction.box.y_max,
                                review_status="pending",
                                inference_settings_json={
                                    "confidence_threshold": (
                                        inference_settings.confidence_threshold
                                    ),
                                    "iou_threshold": inference_settings.iou_threshold,
                                    "device": inference_settings.device,
                                    "task": model_task,
                                },
                                provenance_json={
                                    "provider_name": provider_name,
                                    "provider_version": provider_version,
                                    "model_task": model_task,
                                    "proposal_geometry": geometry_kind,
                                    **raster_metadata,
                                    **_model_source_provenance(model_metadata),
                                },
                            )
                        )
                session.add_all(proposals)
                job.progress_current = index
                previous = dict(job.result_json or {})
                job.result_json = {
                    "processed_images": index,
                    "model_task": model_task,
                    "proposal_count": int(previous.get("proposal_count", 0)) + len(proposals),
                    "mask_proposal_count": int(previous.get("mask_proposal_count", 0))
                    + sum(
                        1
                        for item in proposals
                        if item.geometry_kind in {"polygon_mask", "raster_mask"}
                    ),
                }
                if index == len(image_ids):
                    job.status = "succeeded"
                    job.completed_at = _utc_now()
                session.commit()
                uncommitted_mask_paths.clear()
        return True
    except Exception as exc:
        if project_storage_root is not None:
            for relative_path, proposal_id in tuple(uncommitted_mask_paths.items()):
                with suppress(Exception):
                    remove_prediction_mask_png(
                        settings,
                        project_storage_root=project_storage_root,
                        proposal_id=proposal_id,
                        relative_path=relative_path,
                    )
        uncommitted_mask_paths.clear()
        committed_mask_paths: set[tuple[str, str]] = set()
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                if model_task in {"segment", SEMANTIC_SEGMENTATION_TASK}:
                    partial_proposals = list(
                        session.scalars(
                            select(PredictionProposal).where(
                                PredictionProposal.inference_job_id == job_id
                            )
                        )
                    )
                    for proposal in partial_proposals:
                        if proposal.mask_path is not None:
                            committed_mask_paths.add((proposal.id, proposal.mask_path))
                        session.delete(proposal)
                job.status = "failed"
                job.error_message = str(exc)
                job.result_json = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "model_task": model_task,
                }
                job.completed_at = _utc_now()
                session.commit()
        if project_storage_root is not None:
            for proposal_id, relative_path in committed_mask_paths:
                with suppress(Exception):
                    remove_prediction_mask_png(
                        settings,
                        project_storage_root=project_storage_root,
                        proposal_id=proposal_id,
                        relative_path=relative_path,
                    )
        return False
    finally:
        if provider is not None:
            provider.unload_model()
