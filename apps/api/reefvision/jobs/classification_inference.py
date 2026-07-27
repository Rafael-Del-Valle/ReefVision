"""Background classification inference for images, boxes, masks, and fragments."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ClassificationPrediction,
    ImageAsset,
    Job,
    LabelClass,
    MaskAnnotation,
    ModelRegistration,
)
from reefvision.ml.classification import (
    CLASSIFICATION_TASK,
    CLASSIFIER_PURPOSE,
    UltralyticsClassificationProvider,
)
from reefvision.storage.models import resolve_verified_model_path
from reefvision.storage.projects import resolve_managed_project_path


@dataclass(slots=True)
class _TargetCrop:
    target_kind: str
    target_key: str
    annotation_id: str | None
    mask_annotation_id: str | None
    fragment_key: str | None
    source_label_class_id: str | None
    source_revision: int
    left: int
    top: int
    right: int
    bottom: int
    crop: Image.Image
    provenance: dict[str, Any]


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
    source_label_class_id: str | None,
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
        (item for item in project_classes if item.id == source_label_class_id),
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


def _padded_bounds(
    *,
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    image_width: int,
    image_height: int,
    padding_fraction: float,
) -> tuple[int, int, int, int]:
    width = x_max - x_min
    height = y_max - y_min
    padding_x = width * padding_fraction
    padding_y = height * padding_fraction
    return (
        max(0, int(x_min - padding_x)),
        max(0, int(y_min - padding_y)),
        min(image_width, int(x_max + padding_x + 0.999999)),
        min(image_height, int(y_max + padding_y + 0.999999)),
    )


def _masked_crop(
    settings: Settings,
    source_rgb: Image.Image,
    image: ImageAsset,
    mask: MaskAnnotation,
    bounds: tuple[int, int, int, int],
    *,
    background: str,
) -> Image.Image:
    left, top, _right, _bottom = bounds
    crop = source_rgb.crop(bounds)
    if background == "keep":
        return crop
    local_mask = Image.new("L", crop.size, 0)
    if mask.polygon_json and len(mask.polygon_json) >= 3:
        points = [(float(point[0]) - left, float(point[1]) - top) for point in mask.polygon_json]
        ImageDraw.Draw(local_mask).polygon(points, fill=255)
    elif mask.mask_path:
        mask_path = resolve_managed_project_path(settings, mask.mask_path)
        with Image.open(mask_path) as source_mask:
            grayscale = source_mask.convert("L")
            if grayscale.size != (image.width_px, image.height_px):
                raise RuntimeError("Classification mask dimensions do not match the source image")
            local_mask = grayscale.crop(bounds).point(lambda value: 255 if value else 0)
    else:
        raise RuntimeError("Classification mask has no usable polygon or raster geometry")
    return Image.composite(crop, Image.new("RGB", crop.size, (0, 0, 0)), local_mask)


def _annotation_targets(
    source_rgb: Image.Image,
    image: ImageAsset,
    annotations: list[Annotation],
    *,
    minimum_crop_size_px: int,
    padding_fraction: float,
) -> tuple[list[_TargetCrop], int]:
    targets: list[_TargetCrop] = []
    removed = 0
    for annotation in annotations:
        width = annotation.x_max - annotation.x_min
        height = annotation.y_max - annotation.y_min
        if width < minimum_crop_size_px or height < minimum_crop_size_px:
            removed += 1
            continue
        bounds = _padded_bounds(
            x_min=annotation.x_min,
            y_min=annotation.y_min,
            x_max=annotation.x_max,
            y_max=annotation.y_max,
            image_width=image.width_px,
            image_height=image.height_px,
            padding_fraction=padding_fraction,
        )
        left, top, right, bottom = bounds
        if right <= left or bottom <= top:
            removed += 1
            continue
        targets.append(
            _TargetCrop(
                target_kind="annotation",
                target_key=f"annotation:{annotation.id}",
                annotation_id=annotation.id,
                mask_annotation_id=None,
                fragment_key=None,
                source_label_class_id=annotation.label_class_id,
                source_revision=annotation.revision,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                crop=source_rgb.crop(bounds),
                provenance={"source_annotation_revision": annotation.revision},
            )
        )
    return targets, removed


def _image_target(source_rgb: Image.Image, image: ImageAsset) -> _TargetCrop:
    return _TargetCrop(
        target_kind="image",
        target_key=f"image:{image.id}",
        annotation_id=None,
        mask_annotation_id=None,
        fragment_key=None,
        source_label_class_id=None,
        source_revision=image.annotation_revision,
        left=0,
        top=0,
        right=image.width_px,
        bottom=image.height_px,
        crop=source_rgb.copy(),
        provenance={
            "source_image_annotation_revision": image.annotation_revision,
            "source_image_checksum": image.sha256,
        },
    )


def _mask_targets(
    settings: Settings,
    source_rgb: Image.Image,
    image: ImageAsset,
    masks: list[MaskAnnotation],
    *,
    target_kind: str,
    minimum_crop_size_px: int,
    padding_fraction: float,
    background: str,
) -> tuple[list[_TargetCrop], int]:
    targets: list[_TargetCrop] = []
    removed = 0
    for mask in masks:
        if None in {mask.x_min, mask.y_min, mask.x_max, mask.y_max}:
            removed += 1
            continue
        width = float(mask.x_max) - float(mask.x_min)
        height = float(mask.y_max) - float(mask.y_min)
        if width < minimum_crop_size_px or height < minimum_crop_size_px:
            removed += 1
            continue
        bounds = _padded_bounds(
            x_min=float(mask.x_min),
            y_min=float(mask.y_min),
            x_max=float(mask.x_max),
            y_max=float(mask.y_max),
            image_width=image.width_px,
            image_height=image.height_px,
            padding_fraction=padding_fraction,
        )
        left, top, right, bottom = bounds
        if right <= left or bottom <= top:
            removed += 1
            continue
        raw_fragment_key = dict(mask.provenance_json or {}).get("fragment_key")
        fragment_key = str(raw_fragment_key) if raw_fragment_key else mask.id
        key = f"fragment:{fragment_key}" if target_kind == "fragment" else f"mask:{mask.id}"
        targets.append(
            _TargetCrop(
                target_kind=target_kind,
                target_key=key,
                annotation_id=None,
                mask_annotation_id=mask.id,
                fragment_key=fragment_key if target_kind == "fragment" else None,
                source_label_class_id=mask.label_class_id,
                source_revision=mask.revision,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                crop=_masked_crop(
                    settings,
                    source_rgb,
                    image,
                    mask,
                    bounds,
                    background=background,
                ),
                provenance={
                    "source_mask_revision": mask.revision,
                    "source_mask_geometry_kind": mask.geometry_kind,
                    "source_mask_path": mask.mask_path,
                },
            )
        )
    return targets, removed


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
            or model.project_id != job.project_id
            or model.purpose != CLASSIFIER_PURPOSE
            or model.task != CLASSIFICATION_TASK
        ):
            job.status = "failed"
            job.error_message = "Classification inference requires a registered project classifier"
            job.completed_at = _utc_now()
            session.commit()
            return False
        queued_model_checksum = str(request.get("model_checksum") or "").casefold()
        if not queued_model_checksum or queued_model_checksum != model.sha256.casefold():
            job.status = "failed"
            job.error_message = (
                "The registered classifier changed after this inference job was queued"
            )
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
        model_managed_path = model.managed_path
        model_id = model.id
        project_id = model.project_id
        model_checksum = queued_model_checksum
        model_provider = model.provider_name
        model_provider_version = model.provider_version
        classification_mode = str(model.class_map_json.get("classification_mode", "multiclass"))
        registered_probability_labels = _registered_probability_labels(model)
        image_ids = [str(item) for item in request.get("image_ids", [])]
        selected_mask_ids = {str(item) for item in request.get("mask_annotation_ids", [])}
        target_kind = str(request.get("target_kind", "annotation"))
        device = str(request.get("device", "auto"))
        minimum_crop_size_px = int(request.get("minimum_crop_size_px", 10))
        padding_fraction = float(request.get("padding_fraction", 0.0))
        mask_background = str(request.get("mask_background", "black"))
        label_set = str(request.get("label_set", "default"))

    provider = UltralyticsClassificationProvider()
    temporary_root = settings.resolved_data_dir / ".classification-inference" / job_id
    shutil.rmtree(temporary_root, ignore_errors=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    try:
        model_path = resolve_verified_model_path(
            settings,
            model_managed_path,
            expected_sha256=model_checksum,
        )
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
                source_path = resolve_managed_project_path(settings, image.managed_path)
                with Image.open(source_path) as source:
                    source_rgb = source.convert("RGB")
                    if target_kind == "annotation":
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
                        targets, removed = _annotation_targets(
                            source_rgb,
                            image,
                            annotations,
                            minimum_crop_size_px=minimum_crop_size_px,
                            padding_fraction=padding_fraction,
                        )
                    elif target_kind == "image":
                        targets = [_image_target(source_rgb, image)]
                        removed = 0
                    elif target_kind in {"mask", "fragment"}:
                        query = select(MaskAnnotation).where(
                            MaskAnnotation.image_id == image.id,
                            MaskAnnotation.deleted_at.is_(None),
                            MaskAnnotation.status == "verified",
                        )
                        if selected_mask_ids:
                            query = query.where(MaskAnnotation.id.in_(selected_mask_ids))
                        masks = list(
                            session.scalars(
                                query.order_by(MaskAnnotation.created_at, MaskAnnotation.id)
                            )
                        )
                        targets, removed = _mask_targets(
                            settings,
                            source_rgb,
                            image,
                            masks,
                            target_kind=target_kind,
                            minimum_crop_size_px=minimum_crop_size_px,
                            padding_fraction=padding_fraction,
                            background=mask_background,
                        )
                    else:
                        raise RuntimeError("Classification job has an unsupported target kind")
                    removed_count += removed

                    for target in targets:
                        target_token = target.annotation_id or target.mask_annotation_id or image.id
                        crop_path = temporary_root / f"{target.target_kind}-{target_token}.jpg"
                        try:
                            target.crop.save(crop_path, format="JPEG", quality=95)
                            result = provider.predict(crop_path, device=device)
                        finally:
                            target.crop.close()
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
                            source_label_class_id=target.source_label_class_id,
                            predicted_label=result.label,
                            project_classes=project_classes,
                        )
                        if resolved_class_id is None:
                            unresolved_count += 1
                        session.add(
                            ClassificationPrediction(
                                project_id=project_id,
                                image_id=image.id,
                                annotation_id=target.annotation_id,
                                mask_annotation_id=target.mask_annotation_id,
                                target_kind=target.target_kind,
                                target_key=target.target_key,
                                fragment_key=target.fragment_key,
                                model_id=model_id,
                                inference_job_id=job_id,
                                label_set=label_set,
                                classification_mode=classification_mode,
                                x_min=float(target.left),
                                y_min=float(target.top),
                                x_max=float(target.right),
                                y_max=float(target.bottom),
                                predicted_label=result.label,
                                predicted_index=result.class_index,
                                label_class_id=resolved_class_id,
                                confidence=result.confidence,
                                probabilities_json=result.probabilities,
                                review_status="pending",
                                inference_settings_json={
                                    "target_kind": target_kind,
                                    "device": device,
                                    "minimum_crop_size_px": minimum_crop_size_px,
                                    "padding_fraction": padding_fraction,
                                    "mask_background": mask_background,
                                },
                                provenance_json={
                                    "provider_name": model_provider,
                                    "provider_version": model_provider_version,
                                    "model_checksum": model_checksum,
                                    **target.provenance,
                                    "crop_bbox": [
                                        target.left,
                                        target.top,
                                        target.right,
                                        target.bottom,
                                    ],
                                    "preprocessing_note": (
                                        f"{target_kind} targets smaller than "
                                        f"{minimum_crop_size_px}x{minimum_crop_size_px} pixels "
                                        "were removed during preprocessing."
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
                    "target_kind": target_kind,
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
