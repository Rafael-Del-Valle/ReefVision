"""Evaluate frozen images without creating editable prediction proposals."""

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, ImageAsset, Job, ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.static_count_agreement import prediction_class
from reefvision.jobs.inference import _validate_model_prediction
from reefvision.ml.provider_hub import detection_provider_for_name
from reefvision.ml.providers import DetectionProvider, DetectionSettings
from reefvision.schemas.static_comparison import (
    StaticEvidence,
    StaticImageResult,
    StaticModelEvidence,
    StaticPrediction,
    StaticReferenceImage,
)
from reefvision.services.static_comparison import STATIC_COMPARISON_JOB, build_snapshot
from reefvision.storage.checkpoint_approvals import require_local_execution_approval
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.static_comparison import verify_static_content


def _predict_image(
    settings: Settings,
    session: Session,
    project_id: str,
    model: StaticModelEvidence,
    image: StaticReferenceImage,
    provider: DetectionProvider,
    inference: DetectionSettings,
) -> StaticImageResult:
    asset = session.get(ImageAsset, str(image.id))
    if asset is None or asset.project_id != project_id:
        return StaticImageResult(
            image_id=image.id, status="prediction_missing", message="Source image is unavailable"
        )
    try:
        if asset.sha256 != image.image_sha256:
            raise ValidationError("Source image differs from the frozen reference")
        path = verify_static_content(settings, asset.managed_path, image.image_sha256, fresh=True)
        predictions = []
        for detection in provider.predict(path, inference):
            box = detection.box
            _validate_model_prediction(
                asset,
                label=detection.label,
                class_index=detection.class_index,
                confidence=detection.confidence,
                box=box,
            )
            predictions.append(
                StaticPrediction(
                    label=detection.label,
                    class_index=detection.class_index,
                    class_id=prediction_class(model, detection.label, detection.class_index),
                    confidence=detection.confidence,
                    box=(box.x_min, box.y_min, box.x_max, box.y_max),
                )
            )
        return StaticImageResult(image_id=image.id, status="inferred", raw_predictions=predictions)
    except NotFoundError as exc:
        return StaticImageResult(image_id=image.id, status="prediction_missing", message=str(exc))
    except Exception as exc:
        return StaticImageResult(image_id=image.id, status="inference_failed", message=str(exc))


def _evaluate_model(
    settings: Settings,
    factory: sessionmaker[Session],
    project_id: str,
    evidence: StaticEvidence,
    model: StaticModelEvidence,
    progress: Callable[[int], bool],
) -> tuple[str | None, list[StaticImageResult]]:
    provider = None
    runtime_version = None
    failure = None
    inference = DetectionSettings(**evidence.options.inference.model_dump())
    results: list[StaticImageResult] = []
    try:
        with factory() as session:
            registration = session.get(ModelRegistration, str(model.id))
            if (
                registration is None
                or registration.project_id != project_id
                or registration.sha256 != model.checkpoint_sha256
                or registration.provider_name != model.provider_name
            ):
                raise ValidationError(
                    "Registered detector changed after this comparison was queued"
                )
            checkpoint = verify_static_content(
                settings, registration.managed_path, model.checkpoint_sha256, fresh=True
            )
            require_local_execution_approval(settings, registration, checkpoint)
        provider = detection_provider_for_name(model.provider_name)
        provider.load_model(checkpoint, inference.device)
        runtime_version = provider.provider_version
    except Exception as exc:
        failure = str(exc)
    try:
        for image in evidence.images:
            if not progress(0):
                break
            if image.exclusion is None:
                if failure is not None or provider is None:
                    result = StaticImageResult(
                        image_id=image.id,
                        status="inference_failed",
                        message=failure,
                    )
                else:
                    with factory() as session:
                        result = _predict_image(
                            settings, session, project_id, model, image, provider, inference
                        )
                results.append(result)
            if not progress(1):
                break
    finally:
        if provider is not None:
            with suppress(Exception):
                provider.unload_model()
    return runtime_version, results


def process_static_comparison_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        now = datetime.now(UTC)
        claimed = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.job_type == STATIC_COMPARISON_JOB, Job.status == "queued")
            .values(status="running", started_at=now, error_message=None, progress_current=0)
        )
        session.commit()
        if not getattr(claimed, "rowcount", 0):
            return False
        job = session.get(Job, job_id)
        if job is None or job.project_id is None:
            return False
        project_id = job.project_id
        request = job.request_json

    def progress(increment: int) -> bool:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.status != "running":
                return False
            if increment:
                job.progress_current += increment
                session.commit()
            return True

    try:
        inputs = request["evidence"]
        if canonical_json_sha256(inputs) != request["evidence_sha256"]:
            raise ValidationError("Queued comparison evidence checksum does not match")
        evidence = StaticEvidence.model_validate(inputs)
        with factory() as session:
            dataset = session.get(DatasetVersion, str(evidence.options.dataset_version_id))
            if (
                dataset is None
                or dataset.project_id != project_id
                or dataset.manifest_sha256 != evidence.reference_sha256
                or canonical_json_sha256(dataset.manifest_json) != evidence.reference_sha256
            ):
                raise ValidationError("Frozen reference changed after this comparison was queued")
        observations: dict[UUID, tuple[str | None, list[StaticImageResult]]] = {}
        for model in evidence.models:
            if not progress(0):
                break
            observations[model.id] = _evaluate_model(
                settings, factory, project_id, evidence, model, progress
            )
        result: dict[str, Any] | None = None
        if progress(0):
            snapshot = build_snapshot(evidence, observations).model_dump(mode="json")
            result = {
                "snapshot": snapshot,
                "content_sha256": canonical_json_sha256(snapshot),
                "local_reference_sha256": evidence.reference_sha256,
                "source_id_map": {},
            }
        completed = {"status": "succeeded", "result_json": result} if result else None
        return _finish_job(factory, job_id, completed)
    except Exception as exc:
        _finish_job(factory, job_id, {"status": "failed", "error_message": str(exc)})
        return False


def _finish_job(
    factory: sessionmaker[Session],
    job_id: str,
    values: dict[str, Any] | None,
) -> bool:
    with factory() as session:
        now = datetime.now(UTC)
        transition = update(Job).where(Job.id == job_id).values(completed_at=now)
        if values is not None:
            completed = session.execute(transition.where(Job.status == "running").values(**values))
            if getattr(completed, "rowcount", 0):
                session.commit()
                return True
        cancelled = session.execute(
            transition.where(Job.status == "cancel_requested").values(
                status="cancelled", result_json={"stage": "cancelled"}
            )
        )
        session.commit()
        return bool(getattr(cancelled, "rowcount", 0))
