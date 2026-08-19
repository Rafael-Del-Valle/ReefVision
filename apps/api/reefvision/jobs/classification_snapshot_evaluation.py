"""Background held-out evaluation for immutable classification dataset snapshots."""

from __future__ import annotations

import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationDatasetSample,
    ClassificationDatasetSnapshot,
    ImageAsset,
    Job,
    MaskAnnotation,
    ModelRegistration,
    Project,
)
from reefvision.jobs.classification_inference import _masked_crop, _padded_bounds
from reefvision.jobs.classification_snapshot_integrity_runtime import (
    _current_verified_source_path,
)
from reefvision.jobs.classification_snapshot_training import (
    _file_sha256,
    _mask_geometry,
)
from reefvision.ml.classification import (
    CLASSIFICATION_TASK,
    CLASSIFIER_PURPOSE,
    UltralyticsClassificationProvider,
)
from reefvision.services.classification_metrics import (
    ClassificationObservation,
    build_classification_evaluation,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import resolve_verified_model_path
from reefvision.storage.projects import resolve_managed_project_path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _fail_job(factory: sessionmaker[Session], job_id: str, exc: Exception) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = str(exc)
        job.result_json = {
            **dict(job.result_json or {}),
            "stage": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        job.completed_at = _utc_now()
        session.commit()


def _verified_probability_mapping(
    model: ModelRegistration,
    probabilities: dict[str, float],
) -> dict[str, float]:
    mapping = dict(model.class_map_json or {}).get("mapping", {})
    if not isinstance(mapping, dict) or not mapping:
        raise RuntimeError("Registered classifier is missing its project-class mapping")
    by_class_id: dict[str, float] = {}
    for label, raw_probability in probabilities.items():
        class_id = mapping.get(label)
        if not class_id:
            raise RuntimeError(
                f"Classifier probability label {label!r} is not mapped to a project class"
            )
        normalized_class_id = str(class_id)
        by_class_id[normalized_class_id] = (
            by_class_id.get(normalized_class_id, 0.0) + float(raw_probability)
        )
    total = sum(by_class_id.values())
    if total <= 0:
        raise RuntimeError("Classifier returned no mapped probability mass")
    return {class_id: value / total for class_id, value in by_class_id.items()}


def _model_preprocessing(model: ModelRegistration) -> dict[str, Any]:
    metadata = dict(model.metadata_json or {})
    return {
        "minimum_crop_size_px": int(metadata.get("minimum_crop_size_px", 10)),
        "padding_fraction": float(metadata.get("padding_fraction", 0.0)),
        "mask_background": str(metadata.get("mask_background", "black")),
    }


def _render_sample_crop(
    settings: Settings,
    *,
    sample: ClassificationDatasetSample,
    image: ImageAsset,
    mask: MaskAnnotation | None,
    preprocessing: dict[str, Any],
) -> Image.Image | None:
    current_relative = _current_verified_source_path(sample, image)
    source_path = resolve_managed_project_path(settings, current_relative.as_posix())
    if not source_path.is_file():
        raise FileNotFoundError(
            f"Managed source image is missing for held-out evaluation: {sample.image_id}"
        )
    if _file_sha256(source_path).casefold() != sample.source_image_sha256.casefold():
        raise RuntimeError(
            f"Source image bytes changed after classification snapshot creation: {sample.image_id}"
        )
    with Image.open(source_path) as source:
        source_rgb = source.convert("RGB")
        if sample.target_kind == "image":
            return source_rgb.copy()
        if sample.target_kind not in {"mask", "fragment"}:
            raise RuntimeError(
                f"Held-out snapshot target kind is unsupported: {sample.target_kind}"
            )
        if sample.mask_annotation_id is None or mask is None:
            raise RuntimeError(f"Held-out sample is missing its source mask: {sample.target_key}")
        if mask.image_id != image.id or mask.deleted_at is not None:
            raise RuntimeError(f"Held-out sample source mask is unavailable: {sample.target_key}")
        if sample.target_revision is None or mask.revision != sample.target_revision:
            raise RuntimeError(
                f"Source mask changed after classification snapshot creation: {sample.target_key}"
            )
        current_geometry = _mask_geometry(mask)
        if canonical_json_sha256(current_geometry) != sample.target_checksum:
            raise RuntimeError(
                f"Source mask geometry changed after classification snapshot creation: "
                f"{sample.target_key}"
            )
        if dict(sample.geometry_json or {}) != current_geometry:
            raise RuntimeError(
                f"Stored held-out geometry no longer matches source mask: {sample.target_key}"
            )
        if None in {mask.x_min, mask.y_min, mask.x_max, mask.y_max}:
            raise RuntimeError(f"Held-out source mask lacks usable bounds: {sample.target_key}")
        width = float(mask.x_max) - float(mask.x_min)
        height = float(mask.y_max) - float(mask.y_min)
        minimum = int(preprocessing["minimum_crop_size_px"])
        if width < minimum or height < minimum:
            return None
        bounds = _padded_bounds(
            x_min=float(mask.x_min),
            y_min=float(mask.y_min),
            x_max=float(mask.x_max),
            y_max=float(mask.y_max),
            image_width=image.width_px,
            image_height=image.height_px,
            padding_fraction=float(preprocessing["padding_fraction"]),
        )
        left, top, right, bottom = bounds
        if right <= left or bottom <= top:
            return None
        return _masked_crop(
            settings,
            source_rgb,
            image,
            mask,
            bounds,
            background=str(preprocessing["mask_background"]),
        )


def process_classification_snapshot_evaluation_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if (
            job is None
            or job.job_type != "classification_snapshot_evaluation"
            or job.status != "queued"
        ):
            return False
        request = dict(job.request_json or {})
        snapshot_id = str(request.get("snapshot_id") or "")
        model_id = str(request.get("model_id") or "")
        split = str(request.get("split") or "test")
        snapshot = session.get(ClassificationDatasetSnapshot, snapshot_id)
        model = session.get(ModelRegistration, model_id)
        project = session.get(Project, job.project_id)
        if snapshot is None or model is None or project is None:
            job.status = "failed"
            job.error_message = "Held-out evaluation references a missing snapshot, model, or project"
            job.completed_at = _utc_now()
            session.commit()
            return False
        if snapshot.project_id != job.project_id or model.project_id != job.project_id:
            job.status = "failed"
            job.error_message = "Held-out evaluation records do not belong to the same project"
            job.completed_at = _utc_now()
            session.commit()
            return False
        if model.purpose != CLASSIFIER_PURPOSE or model.task != CLASSIFICATION_TASK:
            job.status = "failed"
            job.error_message = "Held-out evaluation requires a registered classifier"
            job.completed_at = _utc_now()
            session.commit()
            return False
        if snapshot.manifest_sha256 != str(request.get("snapshot_manifest_sha256") or ""):
            job.status = "failed"
            job.error_message = "Classification snapshot changed after evaluation was queued"
            job.completed_at = _utc_now()
            session.commit()
            return False
        if model.sha256.casefold() != str(request.get("model_checksum") or "").casefold():
            job.status = "failed"
            job.error_message = "Registered classifier changed after evaluation was queued"
            job.completed_at = _utc_now()
            session.commit()
            return False
        samples = list(
            session.scalars(
                select(ClassificationDatasetSample)
                .where(
                    ClassificationDatasetSample.snapshot_id == snapshot.id,
                    ClassificationDatasetSample.split == split,
                )
                .order_by(
                    ClassificationDatasetSample.group_key,
                    ClassificationDatasetSample.target_key,
                    ClassificationDatasetSample.id,
                )
            )
        )
        if not samples:
            job.status = "failed"
            job.error_message = f"Classification snapshot has no {split!r} evaluation samples"
            job.completed_at = _utc_now()
            session.commit()
            return False
        image_ids = sorted({sample.image_id for sample in samples})
        images = {
            image.id: image
            for image in session.scalars(
                select(ImageAsset).where(
                    ImageAsset.project_id == job.project_id,
                    ImageAsset.id.in_(image_ids),
                )
            )
        }
        mask_ids = sorted(
            {
                str(sample.mask_annotation_id)
                for sample in samples
                if sample.mask_annotation_id is not None
            }
        )
        masks = (
            {
                mask.id: mask
                for mask in session.scalars(
                    select(MaskAnnotation).where(MaskAnnotation.id.in_(mask_ids))
                )
            }
            if mask_ids
            else {}
        )
        if len(images) != len(image_ids) or len(masks) != len(mask_ids):
            job.status = "failed"
            job.error_message = "A held-out snapshot source image or mask no longer exists"
            job.completed_at = _utc_now()
            session.commit()
            return False
        model_managed_path = model.managed_path
        model_checksum = model.sha256
        preprocessing = _model_preprocessing(model)
        snapshot_manifest_sha256 = snapshot.manifest_sha256
        snapshot_target_kind = snapshot.target_kind
        snapshot_label_set_id = snapshot.label_set_id
        model_class_map = dict(model.class_map_json or {})
        device = str(request.get("device") or "auto")
        calibration_bin_count = int(request.get("calibration_bin_count", 10))
        top_k_values = [int(value) for value in request.get("top_k_values", [1, 3, 5])]
        include_curves = bool(request.get("include_curves", True))
        job.status = "running"
        job.started_at = _utc_now()
        job.error_message = None
        job.progress_total = len(samples)
        job.progress_current = 0
        job.result_json = {
            "stage": "running",
            "snapshot_id": snapshot.id,
            "model_id": model.id,
            "split": split,
        }
        session.commit()

    provider = UltralyticsClassificationProvider()
    temporary_root = settings.resolved_data_dir / ".classification-snapshot-evaluation" / job_id
    shutil.rmtree(temporary_root, ignore_errors=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    observations: list[ClassificationObservation] = []
    evaluated_samples: list[dict[str, Any]] = []
    excluded_samples: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        model_path = resolve_verified_model_path(
            settings,
            model_managed_path,
            expected_sha256=model_checksum,
        )
        provider.load_model(model_path, device)
        output_mapping = model_class_map.get("mapping", {})
        if not isinstance(output_mapping, dict) or not output_mapping:
            raise RuntimeError("Registered classifier is missing output-to-project class mapping")

        for index, sample in enumerate(samples, start=1):
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.result_json = {
                        "stage": "cancelled",
                        "evaluated_sample_count": len(evaluated_samples),
                    }
                    job.completed_at = _utc_now()
                    session.commit()
                    return True

            image = images[sample.image_id]
            mask = masks.get(str(sample.mask_annotation_id)) if sample.mask_annotation_id else None
            crop = _render_sample_crop(
                settings,
                sample=sample,
                image=image,
                mask=mask,
                preprocessing=preprocessing,
            )
            if crop is None:
                excluded_samples.append(
                    {
                        "sample_id": sample.id,
                        "sample_sha256": sample.sample_sha256,
                        "target_key": sample.target_key,
                        "reason": "preprocessing_minimum_crop_or_empty_bounds",
                    }
                )
            else:
                sample_path = temporary_root / f"{index:08d}.jpg"
                try:
                    crop.save(sample_path, format="JPEG", quality=95, optimize=True)
                finally:
                    crop.close()
                result = provider.predict(sample_path, device=device)
                predicted_class_id = output_mapping.get(result.label)
                if not predicted_class_id:
                    raise RuntimeError(
                        f"Classifier output label {result.label!r} is not mapped to a project class"
                    )
                truth_ids = list(sample.label_class_ids_json or [])
                if len(truth_ids) != 1:
                    raise RuntimeError(
                        f"Held-out single-label sample has {len(truth_ids)} truth labels: "
                        f"{sample.target_key}"
                    )
                truth_class_id = str(truth_ids[0])
                probabilities = _verified_probability_mapping(model, result.probabilities)
                if truth_class_id not in probabilities:
                    raise RuntimeError(
                        f"Classifier has no probability output for held-out truth class "
                        f"{truth_class_id}"
                    )
                observations.append(
                    ClassificationObservation(
                        actual_label_class_id=truth_class_id,
                        predicted_label_class_id=str(predicted_class_id),
                        confidence=float(result.confidence),
                        probabilities_by_class_id=probabilities,
                    )
                )
                evaluated_samples.append(
                    {
                        "sample_id": sample.id,
                        "sample_sha256": sample.sample_sha256,
                        "target_key": sample.target_key,
                        "image_id": sample.image_id,
                        "mask_annotation_id": sample.mask_annotation_id,
                        "fragment_key": sample.fragment_key,
                        "truth_label_class_id": truth_class_id,
                        "predicted_label_class_id": str(predicted_class_id),
                        "confidence": float(result.confidence),
                        "probabilities_by_class_id": probabilities,
                    }
                )
                sample_path.unlink(missing_ok=True)

            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                job.progress_current = index
                job.result_json = {
                    "stage": "running",
                    "snapshot_id": snapshot_id,
                    "model_id": model_id,
                    "split": split,
                    "processed_sample_count": index,
                    "evaluated_sample_count": len(evaluated_samples),
                    "excluded_sample_count": len(excluded_samples),
                }
                session.commit()

        if excluded_samples:
            warnings.append(
                f"{len(excluded_samples)} frozen samples were excluded because the classifier's "
                "locked preprocessing minimum/bounds made them non-evaluable."
            )
        if not observations:
            raise RuntimeError("No held-out samples remained after locked preprocessing")
        metrics = build_classification_evaluation(
            project_id=project.id,
            model_id=model_id,
            observations=observations,
            calibration_bin_count=calibration_bin_count,
            top_k_values=top_k_values,
            include_curves=include_curves,
            warnings=warnings,
        )
        evaluation_manifest = {
            "schema": "reefvision-classification-snapshot-evaluation-v1",
            "project_id": project.id,
            "classification_dataset_snapshot_id": snapshot_id,
            "snapshot_manifest_sha256": snapshot_manifest_sha256,
            "split": split,
            "snapshot_target_kind": snapshot_target_kind,
            "snapshot_label_set_id": snapshot_label_set_id,
            "model_id": model_id,
            "model_checksum": model_checksum,
            "preprocessing": preprocessing,
            "requested_sample_count": len(samples),
            "evaluated_samples": evaluated_samples,
            "excluded_samples": excluded_samples,
            "metrics_sha256": canonical_json_sha256(metrics.model_dump(mode="json")),
        }
        evaluation_manifest_sha256 = canonical_json_sha256(evaluation_manifest)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            job.status = "succeeded"
            job.progress_current = len(samples)
            job.result_json = {
                "stage": "completed",
                "classification_dataset_snapshot_id": snapshot_id,
                "snapshot_manifest_sha256": snapshot_manifest_sha256,
                "split": split,
                "model_id": model_id,
                "model_checksum": model_checksum,
                "target_kind": snapshot_target_kind,
                "label_set_id": snapshot_label_set_id,
                "preprocessing": preprocessing,
                "requested_sample_count": len(samples),
                "evaluated_sample_count": len(evaluated_samples),
                "excluded_sample_count": len(excluded_samples),
                "evaluation_manifest_sha256": evaluation_manifest_sha256,
                "evaluation_manifest": evaluation_manifest,
                "metrics": metrics.model_dump(mode="json"),
            }
            job.completed_at = _utc_now()
            session.commit()
        return True
    except Exception as exc:
        _fail_job(factory, job_id, exc)
        return False
    finally:
        with suppress(Exception):
            provider.unload_model()
        shutil.rmtree(temporary_root, ignore_errors=True)
