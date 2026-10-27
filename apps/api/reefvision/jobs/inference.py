"""Background detection, instance, and semantic segmentation inference."""

from __future__ import annotations

import os
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, ModelRegistration, PredictionProposal, Project
from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import detection_provider_for_name
from reefvision.ml.providers import DetectionPrediction, DetectionProvider, DetectionSettings
from reefvision.ml.segmentation import (
    SegmentationPrediction,
    SegmentationProvider,
    segmentation_provider_for_name,
)
from reefvision.ml.semantic_segmentation import (
    SEMANTIC_SEGMENTATION_TASK,
    semantic_provider_for_name,
)
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
from reefvision.services.annotations import _polygon_area, _polygon_self_intersects
from reefvision.storage.projects import resolve_managed_project_path


class _InvalidSegmentationPolygonError(ValidationError):
    """A recoverable per-prediction contour error from a segmentation provider."""


def _validate_model_prediction(
    image: ImageAsset,
    *,
    label: str,
    class_index: int | None,
    confidence: float,
    box: Any,
    polygon: list[list[float]] | None = None,
) -> None:
    coordinates = (
        float(box.x_min),
        float(box.y_min),
        float(box.x_max),
        float(box.y_max),
    )
    if not all(isfinite(value) for value in coordinates):
        raise ValidationError("Model prediction box contains non-finite coordinates")
    x_min, y_min, x_max, y_max = coordinates
    if x_max <= x_min or y_max <= y_min:
        raise ValidationError("Model prediction boxes must have positive area")
    if x_min < 0 or y_min < 0 or x_max > image.width_px or y_max > image.height_px:
        raise ValidationError("Model prediction boxes must remain inside the source image")

    normalized_label = str(label).strip()
    if not normalized_label:
        raise ValidationError("Model predictions must include a non-empty label")
    if class_index is not None and int(class_index) < 0:
        raise ValidationError("Model prediction class indices cannot be negative")

    numeric_confidence = float(confidence)
    if not isfinite(numeric_confidence) or not 0.0 <= numeric_confidence <= 1.0:
        raise ValidationError("Model prediction confidence must be finite and between 0 and 1")

    if polygon is None:
        return
    if len(polygon) < 3:
        raise _InvalidSegmentationPolygonError(
            "Segmentation predictions require at least three polygon points"
        )

    points: list[tuple[float, float]] = []
    for raw_point in polygon:
        if len(raw_point) != 2:
            raise _InvalidSegmentationPolygonError(
                "Every segmentation polygon point must contain x and y"
            )
        x, y = float(raw_point[0]), float(raw_point[1])
        if not isfinite(x) or not isfinite(y):
            raise _InvalidSegmentationPolygonError(
                "Segmentation prediction polygons contain non-finite coordinates"
            )
        if x < 0 or y < 0 or x > image.width_px or y > image.height_px:
            raise _InvalidSegmentationPolygonError(
                "Segmentation prediction polygons must remain inside the source image"
            )
        points.append((x, y))

    if len(set(points)) < 3:
        raise _InvalidSegmentationPolygonError(
            "Segmentation predictions require at least three unique points"
        )
    if _polygon_self_intersects(points):
        raise _InvalidSegmentationPolygonError(
            "Segmentation prediction polygons may not self-intersect"
        )
    if _polygon_area(points) <= 0:
        raise _InvalidSegmentationPolygonError(
            "Segmentation prediction polygons must have positive area"
        )


def _cleanup_pending_job_proposals(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> int:
    """Remove only unreviewed outputs from a terminally failed inference job."""

    with factory() as session:
        pending = list(
            session.scalars(
                select(PredictionProposal).where(
                    PredictionProposal.inference_job_id == job_id,
                    PredictionProposal.review_status.in_(("pending", "evaluation_only")),
                )
            )
        )
        for proposal in pending:
            if proposal.mask_path:
                with suppress(OSError, ValidationError):
                    resolve_managed_project_path(settings, proposal.mask_path).unlink(
                        missing_ok=True
                    )
            session.delete(proposal)
        session.commit()
        return len(pending)


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


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    evaluation_only: bool,
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
        # Keep proposal paths short enough for Windows environments whose Python or
        # imaging stack still observes the traditional MAX_PATH boundary. The UUID
        # remains the authoritative identity; the two-character shard only limits
        # directory fan-out and does not encode job or image provenance.
        output_root = resolve_managed_project_path(
            settings,
            f"{project.storage_root}/prediction-masks/{proposal_id[:2]}",
        )
        output_root.mkdir(parents=True, exist_ok=True)
        destination = output_root / f"{proposal_id}.png"
        temporary = output_root / f".{proposal_id}.tmp"
        try:
            binary.save(temporary, format="PNG", optimize=True)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        x_min, y_min, x_max, y_max = bounds
        relative_mask = destination.relative_to(settings.resolved_data_dir).as_posix()
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
                mask_path=relative_mask,
                mask_content_sha256=_file_sha256(destination),
                x_min=float(x_min),
                y_min=float(y_min),
                x_max=float(x_max),
                y_max=float(y_max),
                review_status="evaluation_only" if evaluation_only else "pending",
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
                    "evaluation_only": evaluation_only,
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
        evaluation_only = request.get("evaluation_only") is True
        processed_images = int(job.progress_current or 0)
        if processed_images < 0 or processed_images > len(image_ids):
            job.status = "failed"
            job.error_message = "Inference progress is inconsistent with the requested image set"
            job.completed_at = _utc_now()
            session.commit()
            return False
        remaining_image_ids = image_ids[processed_images:]

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

    try:
        if not remaining_image_ids:
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                job.status = "succeeded"
                job.progress_current = len(image_ids)
                job.completed_at = _utc_now()
                session.commit()
            return True

        if provider is not None:
            provider.load_model(model_path, inference_settings.device)
        for index, image_id in enumerate(
            remaining_image_ids,
            start=processed_images + 1,
        ):
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
                image_path = resolve_managed_project_path(settings, image.managed_path)
                invalid_prediction_errors: list[str] = []

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
                            evaluation_only=evaluation_only,
                        )
                    finally:
                        indexed_path.unlink(missing_ok=True)
                else:
                    if provider is None:
                        raise RuntimeError("Inference provider is unavailable")
                    predictions: Sequence[DetectionPrediction | SegmentationPrediction]
                    if model_task == "segment":
                        predictions = cast(SegmentationProvider, provider).predict(
                            image_path,
                            inference_settings,
                        )
                    else:
                        predictions = cast(DetectionProvider, provider).predict(
                            image_path,
                            inference_settings,
                        )
                    proposals = []
                    for prediction_index, raw_prediction in enumerate(predictions):
                        prediction = cast(
                            DetectionPrediction | SegmentationPrediction,
                            raw_prediction,
                        )
                        polygon = getattr(prediction, "polygon", None)
                        try:
                            _validate_model_prediction(
                                image,
                                label=prediction.label,
                                class_index=prediction.class_index,
                                confidence=prediction.confidence,
                                box=prediction.box,
                                polygon=polygon,
                            )
                        except _InvalidSegmentationPolygonError as exc:
                            invalid_prediction_errors.append(
                                f"Image {image.id} prediction {prediction_index}: {exc}"
                            )
                            continue
                        geometry_kind = "polygon_mask" if polygon is not None else "bounding_box"
                        proposals.append(
                            PredictionProposal(
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
                                x_min=prediction.box.x_min,
                                y_min=prediction.box.y_min,
                                x_max=prediction.box.x_max,
                                y_max=prediction.box.y_max,
                                review_status=("evaluation_only" if evaluation_only else "pending"),
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
                                    "evaluation_only": evaluation_only,
                                },
                            )
                        )
                session.add_all(proposals)
                job.progress_current = index
                previous = dict(job.result_json or {})
                invalid_prediction_count = int(previous.get("invalid_prediction_count", 0)) + len(
                    invalid_prediction_errors
                )
                recorded_errors = [
                    str(item) for item in previous.get("invalid_prediction_errors", [])
                ]
                recorded_errors.extend(invalid_prediction_errors)
                recorded_errors = recorded_errors[:5]
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
                if invalid_prediction_count:
                    job.result_json["invalid_prediction_count"] = invalid_prediction_count
                    job.result_json["invalid_prediction_errors"] = recorded_errors
                if index == len(image_ids):
                    if (
                        model_task == "segment"
                        and job.result_json["proposal_count"] == 0
                        and invalid_prediction_count > 0
                    ):
                        raise ValidationError(
                            "All segmentation predictions were invalid: " + recorded_errors[0]
                        )
                    job.status = "succeeded"
                    job.completed_at = _utc_now()
                session.commit()
        return True
    except Exception as exc:
        cleanup_error: str | None = None
        try:
            removed_pending_proposals = _cleanup_pending_job_proposals(
                settings,
                factory,
                job_id,
            )
        except Exception as cleanup_exc:
            removed_pending_proposals = 0
            cleanup_error = str(cleanup_exc)

        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.result_json = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "model_task": model_task,
                    "removed_pending_proposals": removed_pending_proposals,
                    "cleanup_error": cleanup_error,
                }
                job.completed_at = _utc_now()
                session.commit()
        return False
    finally:
        if provider is not None:
            provider.unload_model()
