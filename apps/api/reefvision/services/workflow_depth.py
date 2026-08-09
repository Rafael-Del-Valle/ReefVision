"""Workflow-native monocular relative-depth inference with immutable file provenance."""

from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, ModelRegistration, Project
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ValidationError
from reefvision.ml.depth_anything_v2_provider import (
    DepthRegistrationProvider,
    TransformersDepthAnythingV2Provider,
)
from reefvision.storage.projects import resolve_managed_project_path

DepthProviderFactory = Callable[[str], DepthRegistrationProvider]


def workflow_depth_provider_for_name(provider_name: str) -> DepthRegistrationProvider:
    normalized = provider_name.strip().casefold()
    if normalized == "depth_anything_v2":
        return TransformersDepthAnythingV2Provider()
    raise ValidationError(f"Unsupported workflow depth provider: {provider_name}")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_depth_map_artifacts(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    image_ids: list[str],
    model_id: str,
    device: str = "auto",
    provider_factory: DepthProviderFactory = workflow_depth_provider_for_name,
) -> dict[str, object]:
    """Generate immutable relative-depth arrays and previews for workflow images."""

    ordered_image_ids = list(dict.fromkeys(str(value) for value in image_ids if value))
    if not ordered_image_ids:
        raise ValidationError("Relative Depth Estimation requires at least one image")

    project = session.get(Project, project_id)
    if project is None:
        raise ValidationError("Project was not found")
    model = session.get(ModelRegistration, model_id)
    if model is None or model.project_id != project_id:
        raise ValidationError("Depth model does not belong to this project")
    if (
        model.purpose != "depth"
        or model.task != "relative_depth"
        or model.provider_name != "depth_anything_v2"
    ):
        raise ValidationError(
            "Relative Depth Estimation requires a registered Depth Anything V2 model"
        )

    images = {
        image.id: image
        for image in session.scalars(
            select(ImageAsset).where(
                ImageAsset.project_id == project_id,
                ImageAsset.id.in_(ordered_image_ids),
            )
        )
    }
    if set(images) != set(ordered_image_ids):
        raise ValidationError("Every depth input image must belong to this project")

    job = Job(
        project_id=project_id,
        job_type="advanced_depth",
        status="running",
        progress_current=0,
        progress_total=len(ordered_image_ids),
        request_json={
            "workflow_operation": "relative_depth_estimation",
            "model_id": model.id,
            "image_ids": ordered_image_ids,
            "device": device,
            "created_by_workflow": True,
        },
        result_json={"stage": "loading_model", "outputs": [], "created_by_workflow": True},
        started_at=utc_now(),
    )
    session.add(job)
    session.commit()
    job_id = job.id

    output_directory = resolve_managed_project_path(
        settings,
        f"{project.storage_root}/derived/depth/{job_id}",
    )
    shutil.rmtree(output_directory, ignore_errors=True)
    provider = provider_factory(model.provider_name)
    outputs: list[dict[str, object]] = []
    try:
        model_path = resolve_managed_project_path(settings, model.managed_path)
        provider.load_model(model_path, device)
        job.result_json = {
            "stage": "inference",
            "outputs": [],
            "created_by_workflow": True,
        }
        session.commit()

        for progress, image_id in enumerate(ordered_image_ids, start=1):
            image = images[image_id]
            source = resolve_managed_project_path(settings, image.managed_path)
            if not source.is_file():
                raise ValidationError(f"Managed source image is missing: {image.id}")
            relative_base = f"{project.storage_root}/derived/depth/{job_id}/{image.id}"
            absolute_base = resolve_managed_project_path(settings, relative_base)
            prediction = provider.predict_depth(
                source,
                absolute_base,
                device=device,
            )
            depth_path = prediction.relative_depth_path
            preview_path = prediction.preview_path
            if not depth_path.is_file():
                raise ValidationError("Depth provider did not write its relative-depth array")
            if preview_path is not None and not preview_path.is_file():
                raise ValidationError("Depth provider declared a missing preview image")
            output = {
                "image_id": image.id,
                "source_image_sha256": image.sha256,
                "model_id": model.id,
                "model_sha256": model.sha256,
                "provider_id": provider.provider_name,
                "provider_version": provider.provider_version,
                "device": device,
                "depth_kind": "relative",
                "metric_units": None,
                "width": prediction.width,
                "height": prediction.height,
                "minimum_value": prediction.minimum_value,
                "maximum_value": prediction.maximum_value,
                "relative_depth_path": depth_path.relative_to(
                    settings.resolved_data_dir
                ).as_posix(),
                "relative_depth_sha256": _file_sha256(depth_path),
                "preview_path": (
                    preview_path.relative_to(settings.resolved_data_dir).as_posix()
                    if preview_path is not None
                    else None
                ),
                "preview_sha256": (
                    _file_sha256(preview_path) if preview_path is not None else None
                ),
            }
            outputs.append(output)
            job.progress_current = progress
            job.result_json = {
                "stage": "inference",
                "outputs": list(outputs),
                "created_by_workflow": True,
            }
            session.commit()

        job.status = "succeeded"
        job.completed_at = utc_now()
        job.result_json = {
            "stage": "complete",
            "outputs": list(outputs),
            "created_by_workflow": True,
        }
        session.commit()
    except Exception as exc:
        session.rollback()
        shutil.rmtree(output_directory, ignore_errors=True)
        failed_job = session.get(Job, job_id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.error_message = str(exc)
            failed_job.completed_at = utc_now()
            failed_job.result_json = {
                "stage": "failed",
                "outputs": [],
                "error_type": type(exc).__name__,
                "error": str(exc),
                "created_by_workflow": True,
            }
            session.commit()
        raise
    finally:
        provider.unload_model()

    return {
        "schema_version": "relative-depth-maps-0001",
        "project_id": project_id,
        "source_model_id": model.id,
        "source_model_sha256": model.sha256,
        "provider_name": provider.provider_name,
        "provider_version": provider.provider_version,
        "depth_job_id": job_id,
        "depth_kind": "relative",
        "metric_units": None,
        "image_ids": ordered_image_ids,
        "count": len(outputs),
        "outputs": outputs,
    }
