"""Background Depth Anything V2 inference with immutable project outputs."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, ModelRegistration, Project
from reefvision.ml.depth_anything_v2_provider import TransformersDepthAnythingV2Provider
from reefvision.storage.projects import resolve_managed_project_path


def _set_job(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
    outputs: list[dict[str, object]] | None = None,
    error: str | None = None,
    completed: bool = False,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress_current = progress
        if error is not None or status in {"succeeded", "cancelled"}:
            job.error_message = error
        result = dict(job.result_json or {})
        if stage is not None:
            result["stage"] = stage
        if outputs is not None:
            result["outputs"] = outputs
        job.result_json = result
        if completed:
            job.completed_at = datetime.now(UTC)
        session.commit()


def _cancel_requested(factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        return job is None or job.status == "cancel_requested"


def _relative_output_base(project_storage_root: str, job_id: str, image_id: str) -> str:
    return f"{project_storage_root}/derived/depth/{job_id}/{image_id}"


def process_advanced_depth_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "advanced_depth" or job.status != "queued":
            return False
        request = dict(job.request_json)
        project = session.get(Project, job.project_id) if job.project_id else None
        model = session.get(ModelRegistration, str(request.get("model_id") or ""))
        image_ids = [str(value) for value in request.get("image_ids", [])]
        if project is None:
            job.status = "failed"
            job.error_message = "Depth job project is missing"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        if (
            model is None
            or model.project_id != project.id
            or model.purpose != "depth"
            or model.provider_name != "depth_anything_v2"
            or model.task != "relative_depth"
        ):
            job.status = "failed"
            job.error_message = "Registered Depth Anything V2 model not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        images = list(
            session.query(ImageAsset).filter(
                ImageAsset.project_id == project.id,
                ImageAsset.id.in_(image_ids),
            )
        )
        images_by_id = {image.id: image for image in images}
        if len(images_by_id) != len(set(image_ids)):
            job.status = "failed"
            job.error_message = "One or more depth images were not found in the project"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        ordered_images = [images_by_id[image_id] for image_id in image_ids]
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.progress_current = 0
        job.progress_total = len(ordered_images)
        job.error_message = None
        job.result_json = {"stage": "loading_model", "outputs": []}
        session.commit()
        model_path = model.managed_path
        model_sha256 = model.sha256
        model_version = model.provider_version
        project_storage_root = project.storage_root

    provider = TransformersDepthAnythingV2Provider()
    output_directory = resolve_managed_project_path(
        settings,
        f"{project_storage_root}/derived/depth/{job_id}",
    )
    shutil.rmtree(output_directory, ignore_errors=True)
    outputs: list[dict[str, object]] = []
    device = str(request.get("device") or "auto")
    try:
        checkpoint = resolve_managed_project_path(settings, model_path)
        provider.load_model(checkpoint, device)
        _set_job(factory, job_id, stage="inference")

        for progress, image in enumerate(ordered_images, start=1):
            if _cancel_requested(factory, job_id):
                provider.unload_model()
                shutil.rmtree(output_directory, ignore_errors=True)
                _set_job(
                    factory,
                    job_id,
                    status="cancelled",
                    stage="cancelled",
                    outputs=[],
                    completed=True,
                )
                return False

            source = resolve_managed_project_path(settings, image.managed_path)
            if not source.is_file():
                raise FileNotFoundError(f"Managed source image is missing: {image.managed_path}")
            relative_base = _relative_output_base(project_storage_root, job_id, image.id)
            absolute_base = resolve_managed_project_path(settings, relative_base)
            prediction = provider.predict_depth(
                source,
                absolute_base,
                device=device,
            )
            outputs.append(
                {
                    "image_id": image.id,
                    "source_image_sha256": image.sha256,
                    "model_id": str(request["model_id"]),
                    "model_sha256": model_sha256,
                    "provider_id": "depth_anything_v2",
                    "provider_version": model_version,
                    "device": device,
                    "depth_kind": "relative",
                    "metric_units": None,
                    "width": prediction.width,
                    "height": prediction.height,
                    "minimum_value": prediction.minimum_value,
                    "maximum_value": prediction.maximum_value,
                    "relative_depth_path": f"{relative_base}.npy",
                    "preview_path": f"{relative_base}.png",
                }
            )
            _set_job(
                factory,
                job_id,
                progress=progress,
                stage="inference",
                outputs=outputs,
            )

        provider.unload_model()
        _set_job(
            factory,
            job_id,
            status="succeeded",
            progress=len(ordered_images),
            stage="complete",
            outputs=outputs,
            completed=True,
        )
        return True
    except Exception as exc:
        provider.unload_model()
        shutil.rmtree(output_directory, ignore_errors=True)
        _set_job(
            factory,
            job_id,
            status="failed",
            stage="failed",
            outputs=[],
            error=str(exc),
            completed=True,
        )
        return False
