"""Background detection and instance-segmentation inference execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PredictionProposal,
)
from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import detection_provider_for_name
from reefvision.ml.providers import (
    DetectionProvider,
    DetectionSettings,
)
from reefvision.ml.segmentation import (
    SegmentationProvider,
    segmentation_provider_for_name,
)
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
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
        model_path = resolve_managed_project_path(
            settings,
            model.managed_path,
        )
        image_ids = [str(image_id) for image_id in request["image_ids"]]
        inference_settings = DetectionSettings(
            confidence_threshold=float(request["confidence_threshold"]),
            iou_threshold=float(request["iou_threshold"]),
            device=str(request.get("device", "auto")),
        )
        model_task = str(request.get("model_task") or model.task or "detect")
        model_provider_name = model.provider_name
        model_provider_version = model.provider_version
        model_id = model.id
        model_checksum = model.sha256
        model_class_map = dict(model.class_map_json or {})

    provider: DetectionProvider | SegmentationProvider
    if model_task == "segment":
        provider = segmentation_provider_for_name(model_provider_name)
    elif model_task == "detect":
        provider = detection_provider_for_name(model_provider_name)
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
        provider.load_model(
            model_path,
            inference_settings.device,
        )
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
                if image is None:
                    raise ValidationError("The inference job references a missing image")
                image_path = resolve_managed_project_path(
                    settings,
                    image.managed_path,
                )
                predictions = provider.predict(
                    image_path,
                    inference_settings,
                )
                proposals: list[PredictionProposal] = []
                for prediction in predictions:
                    polygon = getattr(prediction, "polygon", None)
                    geometry_kind = "polygon_mask" if polygon is not None else "bounding_box"
                    proposals.append(
                        PredictionProposal(
                            project_id=image.project_id,
                            image_id=image.id,
                            model_id=model_id,
                            inference_job_id=job_id,
                            model_checksum=model_checksum,
                            label_class_id=(
                                _mapped_label_class_id(
                                    model_class_map,
                                    prediction.label,
                                )
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
                            review_status="pending",
                            inference_settings_json={
                                "confidence_threshold": (inference_settings.confidence_threshold),
                                "iou_threshold": (inference_settings.iou_threshold),
                                "device": inference_settings.device,
                                "task": model_task,
                            },
                            provenance_json={
                                "provider_name": model_provider_name,
                                "provider_version": (model_provider_version),
                                "model_task": model_task,
                                "proposal_geometry": geometry_kind,
                            },
                        )
                    )
                session.add_all(proposals)
                job.progress_current = index
                previous_result = dict(job.result_json or {})
                job.result_json = {
                    "processed_images": index,
                    "model_task": model_task,
                    "proposal_count": int(previous_result.get("proposal_count", 0))
                    + len(proposals),
                    "mask_proposal_count": int(
                        previous_result.get(
                            "mask_proposal_count",
                            0,
                        )
                    )
                    + sum(1 for item in proposals if item.geometry_kind == "polygon_mask"),
                }
                if index == len(image_ids):
                    job.status = "succeeded"
                    job.completed_at = _utc_now()
                session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.result_json = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "model_task": model_task,
                }
                job.completed_at = _utc_now()
                session.commit()
        return False
    finally:
        provider.unload_model()
