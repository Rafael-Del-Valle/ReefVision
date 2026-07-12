"""Background inference job execution."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, PredictionProposal
from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import detection_provider_for_name
from reefvision.ml.providers import DetectionSettings
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


def _mapped_label_class_id(model: ModelRegistration, label: str) -> str | None:
    mapping = (
        model.class_map_json.get("mapping", {}) if isinstance(model.class_map_json, dict) else {}
    )
    value = mapping.get(label)
    return str(value) if value else None


def process_inference_job(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
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
        detection_settings = DetectionSettings(
            confidence_threshold=float(request["confidence_threshold"]),
            iou_threshold=float(request["iou_threshold"]),
            device=str(request.get("device", "auto")),
        )

    provider = detection_provider_for_name(model.provider_name)
    try:
        provider.load_model(model_path, detection_settings.device)
        for index, image_id in enumerate(image_ids, start=1):
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.completed_at = _utc_now()
                    session.commit()
                    provider.unload_model()
                    return True
                image = ImageRepository(session).get(image_id)
                if image is None:
                    raise ValidationError("The inference job references a missing image")
                image_path = resolve_managed_project_path(settings, image.managed_path)
                predictions = provider.predict(image_path, detection_settings)
                proposals = [
                    PredictionProposal(
                        project_id=image.project_id,
                        image_id=image.id,
                        model_id=model.id,
                        inference_job_id=job_id,
                        model_checksum=model.sha256,
                        label_class_id=_mapped_label_class_id(model, prediction.label),
                        predicted_label=prediction.label,
                        predicted_index=prediction.class_index,
                        confidence=prediction.confidence,
                        x_min=prediction.box.x_min,
                        y_min=prediction.box.y_min,
                        x_max=prediction.box.x_max,
                        y_max=prediction.box.y_max,
                        review_status="pending",
                        inference_settings_json={
                            "confidence_threshold": detection_settings.confidence_threshold,
                            "iou_threshold": detection_settings.iou_threshold,
                            "device": detection_settings.device,
                        },
                        provenance_json={
                            "provider_name": model.provider_name,
                            "provider_version": model.provider_version,
                        },
                    )
                    for prediction in predictions
                ]
                session.add_all(proposals)
                job.progress_current = index
                job.result_json = {
                    "processed_images": index,
                    "proposal_count": int((job.result_json or {}).get("proposal_count", 0))
                    + len(proposals),
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
                job.result_json = {"error_type": type(exc).__name__, "error": str(exc)}
                job.completed_at = _utc_now()
                session.commit()
        return False
    finally:
        provider.unload_model()
