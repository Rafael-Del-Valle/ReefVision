"""Background annotation-crop classification inference."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ClassificationPrediction,
    ImageAsset,
    Job,
    LabelClass,
    ModelRegistration,
)
from reefvision.ml.classification import (
    CLASSIFICATION_TASK,
    CLASSIFIER_PURPOSE,
    UltralyticsClassificationProvider,
)
from reefvision.storage.projects import resolve_managed_project_path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _delete_job_predictions(session: Session, job_id: str) -> None:
    session.execute(
        delete(ClassificationPrediction).where(ClassificationPrediction.inference_job_id == job_id)
    )


def _registered_probability_labels(model: ModelRegistration) -> tuple[str, ...]:
    raw_labels = dict(model.class_map_json or {}).get("labels", [])
    if not isinstance(raw_labels, list):
        return ()
    labels = tuple(str(label) for label in raw_labels)
    if not labels or len(set(labels)) != len(labels):
        return ()
    return labels


def _resolve_class_id(
    *,
    model: ModelRegistration,
    annotation: Annotation,
    predicted_label: str,
    project_classes: list[LabelClass],
) -> str | None:
    class_map = dict(model.class_map_json or {})
    mode = str(class_map.get("classification_mode", "multiclass"))
    if mode == "multiclass":
        mapping = class_map.get("mapping", {})
        if isinstance(mapping, dict):
            value = mapping.get(predicted_label)
            return str(value) if value else None
        return None
    source_class = next(
        (item for item in project_classes if item.id == annotation.label_class_id),
        None,
    )
    if source_class is None or not source_class.scientific_name:
        return None
    predicted_state = predicted_label.strip().casefold()
    for label_class in project_classes:
        if not label_class.is_active:
            continue
        if (
            label_class.scientific_name or ""
        ).strip().casefold() == source_class.scientific_name.strip().casefold() and (
            label_class.state_name or ""
        ).strip().casefold() == predicted_state:
            return label_class.id
    return None


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
        if (
            model is None
            or model.purpose != CLASSIFIER_PURPOSE
            or model.task != CLASSIFICATION_TASK
        ):
            job.status = "failed"
            job.error_message = "Classification inference requires a registered classifier"
            job.completed_at = _utc_now()
            session.commit()
            return False
        existing_predictions = list(
            session.scalars(
                select(ClassificationPrediction).where(
                    ClassificationPrediction.inference_job_id == job_id
                )
            )
        )
        if any(item.review_status != "pending" for item in existing_predictions):
            job.status = "failed"
            job.error_message = (
                "A classification inference retry cannot replace already reviewed proposals"
            )
            job.completed_at = _utc_now()
            session.commit()
            return False
        if existing_predictions:
            _delete_job_predictions(session, job_id)
        job.status = "running"
        job.started_at = _utc_now()
        job.completed_at = None
        job.error_message = None
        job.progress_current = 0
        job.result_json = {"stage": "running"}
        session.commit()
        model_path = resolve_managed_project_path(settings, model.managed_path)
        model_id = model.id
        project_id = model.project_id
        model_checksum = model.sha256
        model_provider = model.provider_name
        model_provider_version = model.provider_version
        classification_mode = str(model.class_map_json.get("classification_mode", "multiclass"))
        registered_probability_labels = _registered_probability_labels(model)
        image_ids = [str(item) for item in request.get("image_ids", [])]
        device = str(request.get("device", "auto"))
        minimum_crop_size_px = int(request.get("minimum_crop_size_px", 10))
        padding_fraction = float(request.get("padding_fraction", 0.0))
        label_set = str(request.get("label_set", "default"))

    provider = UltralyticsClassificationProvider()
    temporary_root = settings.resolved_data_dir / ".classification-inference" / job_id
    shutil.rmtree(temporary_root, ignore_errors=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    try:
        provider.load_model(model_path, device)
        with factory() as session:
            project_classes = list(
                session.scalars(
                    select(LabelClass)
                    .where(LabelClass.project_id == project_id)
                    .order_by(LabelClass.display_order, LabelClass.class_index)
                )
            )

        proposal_count = 0
        removed_count = 0
        unresolved_count = 0
        for image_number, image_id in enumerate(image_ids, start=1):
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    _delete_job_predictions(session, job_id)
                    job.status = "cancelled"
                    job.completed_at = _utc_now()
                    job.progress_current = 0
                    job.result_json = {
                        "stage": "cancelled",
                        "proposal_count": 0,
                    }
                    session.commit()
                    return True
                image = session.get(ImageAsset, image_id)
                if image is None or image.project_id != project_id:
                    raise RuntimeError("Classification job references an invalid image")
                annotations = list(
                    session.scalars(
                        select(Annotation)
                        .where(
                            Annotation.image_id == image.id,
                            Annotation.deleted_at.is_(None),
                        )
                        .order_by(Annotation.created_at, Annotation.id)
                    )
                )
                source_path = resolve_managed_project_path(settings, image.managed_path)
                with Image.open(source_path) as source:
                    source_rgb = source.convert("RGB")
                    for annotation in annotations:
                        width = annotation.x_max - annotation.x_min
                        height = annotation.y_max - annotation.y_min
                        if width < minimum_crop_size_px or height < minimum_crop_size_px:
                            removed_count += 1
                            continue
                        padding_x = width * padding_fraction
                        padding_y = height * padding_fraction
                        left = max(0, int(annotation.x_min - padding_x))
                        top = max(0, int(annotation.y_min - padding_y))
                        right = min(
                            image.width_px,
                            int(annotation.x_max + padding_x + 0.999999),
                        )
                        bottom = min(
                            image.height_px,
                            int(annotation.y_max + padding_y + 0.999999),
                        )
                        if right <= left or bottom <= top:
                            removed_count += 1
                            continue
                        crop_path = temporary_root / f"{annotation.id}.jpg"
                        source_rgb.crop((left, top, right, bottom)).save(
                            crop_path,
                            format="JPEG",
                            quality=95,
                        )
                        result = provider.predict(crop_path, device=device)
                        if (
                            registered_probability_labels
                            and tuple(result.probabilities) != registered_probability_labels
                        ):
                            raise RuntimeError(
                                "Classifier probability labels do not match the registered "
                                "class mapping"
                            )
                        resolved_class_id = _resolve_class_id(
                            model=model,
                            annotation=annotation,
                            predicted_label=result.label,
                            project_classes=project_classes,
                        )
                        if resolved_class_id is None:
                            unresolved_count += 1
                        session.add(
                            ClassificationPrediction(
                                project_id=project_id,
                                image_id=image.id,
                                annotation_id=annotation.id,
                                model_id=model_id,
                                inference_job_id=job_id,
                                label_set=label_set,
                                classification_mode=classification_mode,
                                x_min=annotation.x_min,
                                y_min=annotation.y_min,
                                x_max=annotation.x_max,
                                y_max=annotation.y_max,
                                predicted_label=result.label,
                                predicted_index=result.class_index,
                                label_class_id=resolved_class_id,
                                confidence=result.confidence,
                                probabilities_json=result.probabilities,
                                review_status="pending",
                                inference_settings_json={
                                    "device": device,
                                    "minimum_crop_size_px": minimum_crop_size_px,
                                    "padding_fraction": padding_fraction,
                                },
                                provenance_json={
                                    "provider_name": model_provider,
                                    "provider_version": model_provider_version,
                                    "model_checksum": model_checksum,
                                    "source_annotation_revision": annotation.revision,
                                    "crop_bbox": [left, top, right, bottom],
                                    "preprocessing_note": (
                                        f"Crops smaller than {minimum_crop_size_px}x"
                                        f"{minimum_crop_size_px} pixels were removed during "
                                        "preprocessing."
                                    ),
                                },
                            )
                        )
                        proposal_count += 1
                        crop_path.unlink(missing_ok=True)
                job.progress_current = image_number
                job.result_json = {
                    "processed_images": image_number,
                    "proposal_count": proposal_count,
                    "removed_during_preprocessing_count": removed_count,
                    "unresolved_class_count": unresolved_count,
                    "classification_mode": classification_mode,
                }
                if image_number == len(image_ids):
                    job.status = "succeeded"
                    job.completed_at = _utc_now()
                session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            _delete_job_predictions(session, job_id)
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = _utc_now()
                job.progress_current = 0
                job.result_json = {
                    "stage": "failed",
                    "proposal_count": 0,
                }
                session.commit()
        return False
    finally:
        provider.unload_model()
        shutil.rmtree(temporary_root, ignore_errors=True)
