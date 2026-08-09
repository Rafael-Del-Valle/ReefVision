"""Provider-neutral box-prompt segmentation for workflow-reviewed detections."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ImageAsset,
    Job,
    LabelClass,
    ModelRegistration,
    PredictionProposal,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import assist_provider_for_name
from reefvision.ml.providers import AnnotationAssistProvider, PixelBox
from reefvision.storage.projects import resolve_managed_project_path

AssistProviderFactory = Callable[[str], AnnotationAssistProvider]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_mask(
    settings: Settings,
    *,
    project_storage_root: str,
    proposal_id: str,
    mask: Any,
) -> tuple[str, str, Path]:
    output_root = resolve_managed_project_path(
        settings,
        f"{project_storage_root}/prediction-masks/{proposal_id[:2]}",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{proposal_id}.png"
    temporary = output_root / f".{proposal_id}.tmp"
    try:
        image = Image.fromarray(mask.astype("uint8") * 255, mode="L")
        image.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    relative_path = destination.relative_to(settings.resolved_data_dir).as_posix()
    return relative_path, _file_sha256(destination), destination


def create_prompt_assist_mask_proposals(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    boxes_artifact: WorkflowArtifact,
    model_id: str,
    device: str = "auto",
    provider_factory: AssistProviderFactory = assist_provider_for_name,
) -> dict[str, Any]:
    """Generate pending raster mask proposals from approved box annotations.

    The function uses ReefVision's generic AnnotationAssistProvider protocol, so the workflow
    contract does not depend on SAM1, SAM2, or another future box-prompt provider.
    """

    if boxes_artifact.data_type != "reviewed_boxes":
        raise ValidationError("Prompt Assist Masks requires a reviewed_boxes artifact")
    payload = dict(boxes_artifact.payload_json or {})
    if payload.get("project_id") != project_id:
        raise ValidationError("Reviewed boxes belong to another project")

    annotation_ids = [str(value) for value in payload.get("annotation_ids", [])]
    if not annotation_ids:
        raise ValidationError("Prompt Assist Masks requires at least one reviewed annotation")

    model = session.get(ModelRegistration, model_id)
    if model is None or model.project_id != project_id:
        raise ValidationError("Prompt Assist model does not belong to this project")
    if model.purpose != "assist":
        raise ValidationError("Prompt Assist Masks requires a registered assist model")

    annotations = list(
        session.scalars(
            select(Annotation).where(
                Annotation.id.in_(annotation_ids),
                Annotation.deleted_at.is_(None),
            )
        )
    )
    annotations_by_id = {item.id: item for item in annotations}
    if set(annotations_by_id) != set(annotation_ids):
        raise ValidationError("Every reviewed box annotation must exist and be active")

    image_ids = sorted({annotation.image_id for annotation in annotations})
    images = {
        image.id: image
        for image in session.scalars(
            select(ImageAsset).where(
                ImageAsset.project_id == project_id,
                ImageAsset.id.in_(image_ids),
            )
        )
    }
    if set(images) != set(image_ids):
        raise ValidationError("Every reviewed annotation image must belong to this project")

    class_ids = sorted({annotation.label_class_id for annotation in annotations})
    classes = {
        label_class.id: label_class
        for label_class in session.scalars(
            select(LabelClass).where(
                LabelClass.project_id == project_id,
                LabelClass.id.in_(class_ids),
            )
        )
    }
    if set(classes) != set(class_ids):
        raise ValidationError("Every reviewed annotation class must belong to this project")

    project_storage_root = next(iter(images.values())).project.storage_root if images else None
    if project_storage_root is None:
        # Avoid depending on the image relationship being eagerly loaded.
        from reefvision.db.models import Project

        project = session.get(Project, project_id)
        if project is None:
            raise ValidationError("Project was not found")
        project_storage_root = project.storage_root

    job = Job(
        project_id=project_id,
        job_type="inference",
        status="running",
        progress_current=0,
        progress_total=len(annotation_ids),
        request_json={
            "workflow_operation": "prompt_assist_masks",
            "model_id": model.id,
            "annotation_ids": annotation_ids,
            "device": device,
            "source_artifact_id": boxes_artifact.id,
            "created_by_workflow": True,
        },
        result_json={"stage": "running", "created_by_workflow": True},
    )
    session.add(job)
    session.commit()
    job_id = job.id

    provider = provider_factory(model.provider_name)
    model_path = resolve_managed_project_path(settings, model.managed_path)
    written_paths: list[Path] = []
    proposals: list[PredictionProposal] = []
    prepared_by_image: dict[str, Any] = {}
    try:
        provider.load_model(model_path, device)
        for index, annotation_id in enumerate(annotation_ids, start=1):
            annotation = annotations_by_id[annotation_id]
            image = images[annotation.image_id]
            prepared = prepared_by_image.get(image.id)
            if prepared is None:
                image_path = resolve_managed_project_path(settings, image.managed_path)
                if not image_path.is_file():
                    raise ValidationError(f"Managed image file is missing: {image.id}")
                prepared = provider.prepare_image(image_path)
                prepared_by_image[image.id] = prepared

            prediction = provider.predict_from_box(
                prepared,
                PixelBox(
                    x_min=annotation.x_min,
                    y_min=annotation.y_min,
                    x_max=annotation.x_max,
                    y_max=annotation.y_max,
                ),
            )
            proposal_id = str(uuid4())
            mask_path, mask_sha256, absolute_path = _save_mask(
                settings,
                project_storage_root=project_storage_root,
                proposal_id=proposal_id,
                mask=prediction.mask,
            )
            written_paths.append(absolute_path)
            label_class = classes[annotation.label_class_id]
            proposal = PredictionProposal(
                id=proposal_id,
                project_id=project_id,
                image_id=image.id,
                model_id=model.id,
                inference_job_id=job_id,
                model_checksum=model.sha256,
                label_class_id=label_class.id,
                predicted_label=label_class.name,
                predicted_index=label_class.class_index,
                confidence=float(prediction.score),
                geometry_kind="raster_mask",
                polygon_json=None,
                mask_path=mask_path,
                mask_content_sha256=mask_sha256,
                x_min=prediction.box.x_min,
                y_min=prediction.box.y_min,
                x_max=prediction.box.x_max,
                y_max=prediction.box.y_max,
                review_status="pending",
                inference_settings_json={
                    "device": device,
                    "task": "assist_segmentation",
                    "prompt_kind": "reviewed_box",
                },
                provenance_json={
                    "source": "workflow_prompt_assist",
                    "workflow_artifact_id": boxes_artifact.id,
                    "workflow_run_id": boxes_artifact.workflow_run_id,
                    "input_annotation_id": annotation.id,
                    "provider_name": provider.provider_name,
                    "provider_version": provider.provider_version,
                    "model_id": model.id,
                    "model_sha256": model.sha256,
                    "prompt_box": {
                        "x_min": annotation.x_min,
                        "y_min": annotation.y_min,
                        "x_max": annotation.x_max,
                        "y_max": annotation.y_max,
                    },
                },
            )
            session.add(proposal)
            proposals.append(proposal)
            job.progress_current = index
        job.status = "succeeded"
        job.result_json = {
            "stage": "succeeded",
            "proposal_count": len(proposals),
            "created_by_workflow": True,
        }
        session.commit()
    except Exception as exc:
        session.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        failed_job = session.get(Job, job_id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.error_message = str(exc)
            failed_job.result_json = {
                "stage": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "created_by_workflow": True,
            }
            session.commit()
        raise
    finally:
        provider.unload_model()

    return {
        "schema_version": "mask-proposals-0001",
        "project_id": project_id,
        "source_id": model.id,
        "source_kind": "prompt_assist",
        "source_model_id": model.id,
        "source_model_sha256": model.sha256,
        "provider_name": provider.provider_name,
        "provider_version": provider.provider_version,
        "inference_job_id": job_id,
        "input_artifact_id": boxes_artifact.id,
        "input_annotation_ids": annotation_ids,
        "image_ids": image_ids,
        "proposal_ids": [proposal.id for proposal in proposals],
        "count": len(proposals),
        "masks": [
            {
                "proposal_id": proposal.id,
                "image_id": proposal.image_id,
                "label_class_id": proposal.label_class_id,
                "predicted_label": proposal.predicted_label,
                "confidence": proposal.confidence,
                "geometry_kind": proposal.geometry_kind,
                "mask_path": proposal.mask_path,
                "mask_content_sha256": proposal.mask_content_sha256,
                "box": {
                    "x_min": proposal.x_min,
                    "y_min": proposal.y_min,
                    "x_max": proposal.x_max,
                    "y_max": proposal.y_max,
                },
                "provenance": dict(proposal.provenance_json or {}),
            }
            for proposal in proposals
        ],
    }
