"""Background top-k image classification inference."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationPrediction,
    ImageAsset,
    Job,
    ModelRegistration,
)
from reefvision.ml.classification import classification_provider_for_name
from reefvision.storage.projects import resolve_managed_project_path


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        session.commit()


def process_classification_inference_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "classification_inference" or job.status != "queued":
            return False
        request = dict(job.request_json)
        model = session.get(ModelRegistration, str(request.get("model_id", "")))
        if model is None or model.purpose != "classifier" or model.task != "classify":
            job.status = "failed"
            job.error_message = "Registered classifier model not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        image_ids = [str(value) for value in request.get("image_ids", [])]
        images = list(
            session.query(ImageAsset)
            .filter(
                ImageAsset.id.in_(image_ids),
                ImageAsset.project_id == model.project_id,
            )
            .order_by(ImageAsset.created_at, ImageAsset.id)
        )
        if len(images) != len(set(image_ids)):
            job.status = "failed"
            job.error_message = (
                "One or more classification images were not found in the model project"
            )
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.progress_total = len(images)
        job.progress_current = 0
        job.error_message = None
        session.commit()
        model_path = model.managed_path
        provider_name = model.provider_name
        class_map = dict(model.class_map_json or {})
        project_id = model.project_id

    try:
        provider = classification_provider_for_name(provider_name)
        checkpoint = resolve_managed_project_path(settings, model_path)
        provider_classes_raw = class_map.get("provider_classes", {})
        provider_classes = (
            dict(provider_classes_raw) if isinstance(provider_classes_raw, dict) else {}
        )
        label_set = str(request.get("label_set", class_map.get("label_set", "default")))
        top_k = max(1, int(request.get("top_k", 5)))
        created = 0

        for progress, image in enumerate(images, start=1):
            source = resolve_managed_project_path(settings, image.managed_path)
            scores = provider.predict(
                checkpoint,
                source,
                top_k=top_k,
                device=str(request.get("device", "auto")),
            )
            score_payload = [
                {
                    "class_name": score.class_name,
                    "confidence": score.confidence,
                    "rank": score.rank,
                }
                for score in scores
            ]
            with factory() as session:
                session.execute(
                    delete(ClassificationPrediction).where(
                        ClassificationPrediction.image_id == image.id,
                        ClassificationPrediction.model_id == str(request["model_id"]),
                        ClassificationPrediction.label_set == label_set,
                        ClassificationPrediction.status == "pending",
                    )
                )
                for score in scores:
                    mapped = provider_classes.get(score.class_name)
                    if not isinstance(mapped, dict):
                        continue
                    label_class_id = str(mapped.get("label_class_id", ""))
                    if not label_class_id:
                        continue
                    session.add(
                        ClassificationPrediction(
                            project_id=project_id,
                            image_id=image.id,
                            model_id=str(request["model_id"]),
                            label_class_id=label_class_id,
                            label_set=label_set,
                            confidence=score.confidence,
                            rank=score.rank,
                            scores_json={"top_k": score_payload},
                            status="pending",
                        )
                    )
                    created += 1
                job = session.get(Job, job_id)
                if job is None:
                    raise RuntimeError("Classification inference job disappeared")
                job.progress_current = progress
                session.commit()

        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise RuntimeError("Classification inference job disappeared")
            job.status = "succeeded"
            job.result_json = {
                "prediction_count": created,
                "image_count": len(images),
                "label_set": label_set,
                "top_k": top_k,
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        _fail(factory, job_id, str(exc))
        return False
