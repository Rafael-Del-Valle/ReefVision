"""Unified instance, semantic, and prompt-assisted segmentation for Fusion workflows.

Trained instance/semantic segmenters continue through the production inference worker. SAM,
SAM 2, MobileSAM, FastSAM, and compatible sidecar registrations use detector proposals as
box prompts and create the same pending raster-mask proposal contract. No generated mask is
promoted to an annotation here; explicit review remains mandatory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    Job,
    ModelRegistration,
    PredictionProposal,
    Project,
    WorkflowArtifact,
    WorkflowRun,
)
from reefvision.jobs import workflow_runs
from reefvision.ml.provider_hub import assist_provider_for_name
from reefvision.ml.providers import PixelBox
from reefvision.ml.sam2_sidecar import SAM2SidecarAssistProvider
from reefvision.storage.masks import remove_prediction_mask_png, write_prediction_mask_png
from reefvision.storage.models import resolve_verified_model_path
from reefvision.storage.projects import resolve_managed_project_path

_ORIGINAL_MODEL_INFERENCE = workflow_runs._model_inference
_ASSIST_TASK = "assist_segmentation"


def _assist_provider(provider_name: str) -> Any:
    normalized = provider_name.strip().casefold()
    if normalized == "sam2_sidecar":
        return SAM2SidecarAssistProvider()
    return assist_provider_for_name(provider_name)


def _mask_png_bytes(mask: Any, *, width: int, height: int) -> bytes:
    array = np.asarray(mask)
    array = np.squeeze(array)
    if array.ndim != 2 or array.shape != (height, width):
        raise RuntimeError("Assist segmentation returned a mask with incorrect dimensions")
    try:
        finite = np.isfinite(array)
    except TypeError as exc:
        raise RuntimeError("Assist segmentation returned a non-numeric mask") from exc
    binary = finite & (array > 0)
    if not bool(binary.any()):
        raise RuntimeError("Assist segmentation returned an empty mask")
    stream = BytesIO()
    Image.fromarray(binary.astype(np.uint8) * 255, mode="L").save(
        stream,
        format="PNG",
        optimize=True,
    )
    return stream.getvalue()


def _model_source_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_training_run_id",
        "source_dataset_version_id",
        "source_dataset_manifest_sha256",
        "source_split_manifest_sha256",
        "source_catalog_model_id",
        "source_resolved_model_asset_id",
        "source_resolved_model_checksum",
        "source_result_checkpoint_path",
    )
    return {key: metadata[key] for key in keys if metadata.get(key) is not None}


def _segmentation_mode(task: str) -> str:
    if task == _ASSIST_TASK:
        return "prompt_assisted"
    if task == "semantic_segment":
        return "semantic"
    return "instance"


def _enrich_segmentation_output(
    outputs: workflow_runs.ArtifactOutputs,
    *,
    task: str,
    provider_name: str,
    model_id: str,
) -> workflow_runs.ArtifactOutputs:
    mask_output = outputs.get("masks")
    if mask_output is None:
        return outputs
    artifact_type, raw_payload = mask_output[:2]
    payload = dict(raw_payload)
    accepted_mask_ids = [
        str(value)
        for value in payload.get("mask_annotation_ids", [])
        if value is not None
    ]
    payload.update(
        {
            "model_id": model_id,
            "model_task": task,
            "provider_name": provider_name,
            "segmentation_mode": _segmentation_mode(task),
            "proposal_review_required": not bool(accepted_mask_ids),
            "proposal_review_state": (
                "accepted_masks_available" if accepted_mask_ids else "pending_review"
            ),
        }
    )
    if len(mask_output) == 4:
        return {
            "masks": (
                artifact_type,
                payload,
                mask_output[2],
                mask_output[3],
            )
        }
    return {"masks": (artifact_type, payload)}


def _prompt_assisted_segmentation(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
    *,
    model: ModelRegistration,
) -> workflow_runs.ArtifactOutputs:
    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    image_ids = workflow_runs._list_values(payloads, "image_ids")
    configured_prompts = configuration.get("prompt_prediction_ids")
    prompt_ids = (
        [str(value) for value in configured_prompts]
        if isinstance(configured_prompts, list)
        else workflow_runs._list_values(payloads, "prediction_ids")
    )
    prompt_ids = list(dict.fromkeys(prompt_ids))
    if not prompt_ids:
        raise RuntimeError(
            "Prompt-assisted segmentation requires detector prediction proposals connected "
            "to the Segmenter prompts input"
        )

    with factory() as session:
        project = session.get(Project, run.project_id)
        if project is None:
            raise RuntimeError("Workflow project disappeared before assist segmentation")
        prompts = list(
            session.scalars(
                select(PredictionProposal)
                .where(
                    PredictionProposal.project_id == run.project_id,
                    PredictionProposal.id.in_(prompt_ids),
                )
                .order_by(PredictionProposal.image_id, PredictionProposal.id)
            )
        )
        if len(prompts) != len(prompt_ids):
            raise RuntimeError("One or more prompt predictions are missing from the project")
        if image_ids and any(prompt.image_id not in set(image_ids) for prompt in prompts):
            raise RuntimeError("Prompt predictions must belong to the Segmenter image input")
        prompt_image_ids = list(dict.fromkeys(prompt.image_id for prompt in prompts))
        images = list(
            session.scalars(
                select(ImageAsset).where(
                    ImageAsset.project_id == run.project_id,
                    ImageAsset.id.in_(prompt_image_ids),
                )
            )
        )
        image_by_id = {image.id: image for image in images}
        if len(image_by_id) != len(prompt_image_ids):
            raise RuntimeError("One or more prompt source images are missing")
        child = Job(
            project_id=run.project_id,
            job_type="inference",
            status="running",
            progress_total=max(len(prompts), 1),
            progress_current=0,
            request_json={
                "model_id": model.id,
                "model_task": _ASSIST_TASK,
                "image_ids": prompt_image_ids,
                "prompt_prediction_ids": prompt_ids,
                "device": str(configuration.get("device", "auto")),
                "source_kind": "workflow_prompt_assist",
                "parent_workflow_run_id": run.id,
            },
            result_json={"stage": "prompt_assist_segmentation"},
            started_at=datetime.now(UTC),
        )
        session.add(child)
        session.commit()
        session.refresh(child)
        child_id = child.id
        project_storage_root = project.storage_root

    model_path = resolve_verified_model_path(
        settings,
        model.managed_path,
        expected_sha256=model.sha256,
    )
    provider = _assist_provider(model.provider_name)
    provider.load_model(model_path, str(configuration.get("device", "auto")))
    stored_masks: list[tuple[str, str]] = []
    proposals_to_add: list[PredictionProposal] = []
    try:
        prepared_by_image: dict[str, Any] = {}
        for index, prompt in enumerate(prompts, start=1):
            image = image_by_id[prompt.image_id]
            prepared = prepared_by_image.get(image.id)
            if prepared is None:
                image_path = resolve_managed_project_path(settings, image.managed_path)
                prepared = provider.prepare_image(image_path)
                prepared_by_image[image.id] = prepared
            box = PixelBox(
                x_min=float(prompt.x_min),
                y_min=float(prompt.y_min),
                x_max=float(prompt.x_max),
                y_max=float(prompt.y_max),
            )
            if not (
                0 <= box.x_min < box.x_max <= image.width_px
                and 0 <= box.y_min < box.y_max <= image.height_px
            ):
                raise RuntimeError("Prompt proposal bounds fall outside the source image")
            prediction = provider.predict_from_box(prepared, box)
            proposal_id = str(uuid4())
            stored = write_prediction_mask_png(
                settings,
                project_storage_root=project_storage_root,
                proposal_id=proposal_id,
                png_bytes=_mask_png_bytes(
                    prediction.mask,
                    width=image.width_px,
                    height=image.height_px,
                ),
                expected_width=image.width_px,
                expected_height=image.height_px,
            )
            stored_masks.append((proposal_id, stored.relative_path))
            confidence = min(float(prompt.confidence), float(prediction.score))
            proposals_to_add.append(
                PredictionProposal(
                    id=proposal_id,
                    project_id=run.project_id,
                    image_id=image.id,
                    model_id=model.id,
                    inference_job_id=child_id,
                    model_checksum=model.sha256,
                    label_class_id=prompt.label_class_id,
                    predicted_label=prompt.predicted_label,
                    predicted_index=prompt.predicted_index,
                    confidence=confidence,
                    geometry_kind="raster_mask",
                    polygon_json=None,
                    mask_path=stored.relative_path,
                    mask_content_sha256=stored.content_sha256,
                    x_min=float(stored.x_min),
                    y_min=float(stored.y_min),
                    x_max=float(stored.x_max),
                    y_max=float(stored.y_max),
                    review_status="pending",
                    inference_settings_json={
                        "device": str(configuration.get("device", "auto")),
                        "task": _ASSIST_TASK,
                        "prompt_type": "box_to_mask",
                        "source_prediction_id": prompt.id,
                    },
                    provenance_json={
                        "provider_name": model.provider_name,
                        "provider_version": provider.provider_version,
                        "model_task": _ASSIST_TASK,
                        "proposal_geometry": "raster_mask",
                        "source_prediction_id": prompt.id,
                        "source_prediction_model_id": prompt.model_id,
                        "source_prediction_confidence": prompt.confidence,
                        "assist_score": float(prediction.score),
                        "area_pixels": stored.area_pixels,
                        "review_before_accept": True,
                        **_model_source_provenance(dict(model.metadata_json or {})),
                    },
                )
            )
            with factory() as session:
                child = session.get(Job, child_id)
                if child is None:
                    raise RuntimeError("Assist segmentation child job disappeared")
                child.progress_current = index
                child.result_json = {
                    "stage": "prompt_assist_segmentation",
                    "processed_prompts": index,
                    "proposal_count": len(proposals_to_add),
                }
                session.commit()

        with factory() as session:
            session.add_all(proposals_to_add)
            child = session.get(Job, child_id)
            if child is None:
                raise RuntimeError("Assist segmentation child job disappeared")
            child.status = "succeeded"
            child.completed_at = datetime.now(UTC)
            child.result_json = {
                "stage": "completed",
                "model_task": _ASSIST_TASK,
                "proposal_count": len(proposals_to_add),
                "mask_proposal_count": len(proposals_to_add),
                "prompt_prediction_ids": prompt_ids,
            }
            session.commit()
        return {
            "masks": (
                "masks",
                {
                    "image_ids": prompt_image_ids,
                    "prediction_ids": [proposal.id for proposal in proposals_to_add],
                    "prompt_prediction_ids": prompt_ids,
                    "mask_annotation_ids": [],
                    "model_id": model.id,
                    "model_task": _ASSIST_TASK,
                    "provider_name": model.provider_name,
                    "provider_version": provider.provider_version,
                    "segmentation_mode": "prompt_assisted",
                    "geometry_kind": "raster_mask",
                    "child_job_id": child_id,
                    "proposal_review_required": True,
                    "proposal_review_state": "pending_review",
                    "review_before_accept": True,
                },
            )
        }
    except Exception as exc:
        with factory() as session:
            child = session.get(Job, child_id)
            if child is not None:
                child.status = "failed"
                child.error_message = str(exc)
                child.completed_at = datetime.now(UTC)
                session.commit()
        for proposal_id, relative_path in stored_masks:
            remove_prediction_mask_png(
                settings,
                project_storage_root=project_storage_root,
                proposal_id=proposal_id,
                relative_path=relative_path,
            )
        raise
    finally:
        provider.unload_model()


def _unified_model_inference(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    node_type: str,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    if node_type != "segmenter":
        return _ORIGINAL_MODEL_INFERENCE(
            settings,
            factory,
            run,
            node_type,
            configuration,
            inputs,
        )
    model_id = str(configuration.get("model_id", "")).strip()
    if not model_id:
        raise RuntimeError("Segmenter nodes require model_id")
    with factory() as session:
        model = session.get(ModelRegistration, model_id)
        if model is None or model.project_id != run.project_id:
            raise RuntimeError("The selected segmentation model is not registered in this project")
        task = str(model.task or "").strip().casefold()
        provider_name = model.provider_name
    if task == _ASSIST_TASK:
        return _prompt_assisted_segmentation(
            settings,
            factory,
            run,
            configuration,
            inputs,
            model=model,
        )
    outputs = _ORIGINAL_MODEL_INFERENCE(
        settings,
        factory,
        run,
        node_type,
        configuration,
        inputs,
    )
    return _enrich_segmentation_output(
        outputs,
        task=task,
        provider_name=provider_name,
        model_id=model_id,
    )


workflow_runs._model_inference = _unified_model_inference
