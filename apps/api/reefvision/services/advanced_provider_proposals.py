"""Persist Advanced Provider outputs in ReefVision's standard prediction-review system."""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    Job,
    LabelClass,
    ModelRegistration,
    PredictionProposal,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.optional_transformers_runtime import OPTIONAL_MODEL_SPECS
from reefvision.storage.projects import resolve_managed_project_path

_PROVIDER_CATALOG_IDS = {
    "grounding_dino": "transformers/grounding_dino/tiny",
    "sam2": "sam2/image/base",
}

_PROVIDER_REGISTRATION = {
    "grounding_dino": ("detector", "open_vocabulary_detect"),
    "sam2": ("assist", "assist_segmentation"),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _image(session: Session, project_id: str, image_id: str) -> ImageAsset:
    image = session.get(ImageAsset, image_id)
    if image is None or image.project_id != project_id:
        raise ValidationError("Advanced Provider image does not belong to the selected project")
    return image


def _catalog_proxy_name(provider_id: str) -> str:
    return f"ReefVision managed · {OPTIONAL_MODEL_SPECS[provider_id].display_name}"


def _ensure_catalog_proxy_registration(
    session: Session,
    settings: Settings,
    *,
    project: Project,
    provider_id: str,
    runtime_path: Path,
    source_repo_id: str | None = None,
    source_revision: str | None = None,
    source_checksum: str | None = None,
    source_variant: str | None = None,
) -> ModelRegistration:
    """Create a project FK/provenance record without duplicating model weights."""

    spec = OPTIONAL_MODEL_SPECS[provider_id]
    catalog_id = (
        f"sam2/image/{source_variant}"
        if provider_id == "sam2" and source_variant
        else _PROVIDER_CATALOG_IDS[provider_id]
    )
    purpose, task = _PROVIDER_REGISTRATION[provider_id]
    display_name = (
        f"ReefVision managed · SAM 2.1 Hiera {source_variant}"
        if provider_id == "sam2" and source_variant
        else _catalog_proxy_name(provider_id)
    )
    resolved_repo = source_repo_id or spec.repo_id
    resolved_revision = source_revision or spec.revision
    resolved_checksum = source_checksum or spec.weight_sha256

    existing = session.scalar(
        select(ModelRegistration).where(
            ModelRegistration.project_id == project.id,
            ModelRegistration.display_name == display_name,
        )
    )
    if existing is not None:
        return existing

    marker = {
        "schema_version": "reefvision-managed-catalog-proxy-0001",
        "project_id": project.id,
        "provider_id": provider_id,
        "catalog_id": catalog_id,
        "repo_id": resolved_repo,
        "revision": resolved_revision,
        "checkpoint_sha256": resolved_checksum,
        "runtime_path": str(runtime_path),
    }
    marker_bytes = (json.dumps(marker, sort_keys=True, indent=2) + "\n").encode("utf-8")
    suffix = f"-{source_variant}" if provider_id == "sam2" and source_variant else ""
    relative_path = (
        f"{project.storage_root}/models/catalog-proxies/{provider_id}{suffix}.catalog-link.json"
    )
    marker_path = resolve_managed_project_path(settings, relative_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker_path.with_suffix(marker_path.suffix + ".tmp")
    try:
        temporary.write_bytes(marker_bytes)
        os.replace(temporary, marker_path)
    finally:
        temporary.unlink(missing_ok=True)

    registration = ModelRegistration(
        project_id=project.id,
        purpose=purpose,
        display_name=display_name,
        source_filename=marker_path.name,
        managed_path=relative_path,
        sha256=_sha256_bytes(marker_bytes),
        file_size_bytes=len(marker_bytes),
        framework="transformers",
        task=task,
        provider_name=provider_id,
        provider_version=f"pinned:{resolved_revision[:12]}",
        class_map_json={},
        input_size_json=None,
        metadata_json={
            "managed_catalog_proxy": True,
            "hidden_from_normal_model_selection": True,
            "catalog_id": catalog_id,
            "repo_id": resolved_repo,
            "revision": resolved_revision,
            "checkpoint_sha256": resolved_checksum,
            "runtime_path": str(runtime_path),
            "runtime_managed_by": "model_hub",
        },
        notes=(
            "Internal provenance link for a shared Model Hub checkpoint. "
            "The actual model weights are not duplicated into this project."
        ),
    )
    session.add(registration)
    session.flush()
    return registration


def _new_inference_job(
    session: Session,
    *,
    project_id: str,
    model_id: str,
    provider_id: str,
    task: str,
    image_id: str,
    device: str,
    prompt_fields: dict[str, Any],
) -> Job:
    job = Job(
        project_id=project_id,
        job_type="inference",
        status="running",
        progress_current=0,
        progress_total=1,
        request_json={
            "source": "advanced_provider",
            "provider_id": provider_id,
            "task": task,
            "model_id": model_id,
            "image_ids": [image_id],
            "device": device,
            "prompt_fields": prompt_fields,
        },
        result_json={"stage": "running", "source": "advanced_provider"},
        started_at=_utc_now(),
    )
    session.add(job)
    session.flush()
    return job


def _complete_job(job: Job, proposal_ids: list[str]) -> None:
    job.status = "succeeded"
    job.progress_current = 1
    job.completed_at = _utc_now()
    job.result_json = {
        "stage": "succeeded",
        "source": "advanced_provider",
        "proposal_count": len(proposal_ids),
        "proposal_ids": proposal_ids,
    }


def _active_class_for_label(
    session: Session,
    *,
    project_id: str,
    label: str,
) -> LabelClass | None:
    normalized = label.strip().casefold()
    if not normalized:
        return None
    classes = list(session.scalars(select(LabelClass).where(LabelClass.project_id == project_id)))
    return next(
        (item for item in classes if item.is_active and item.name.strip().casefold() == normalized),
        None,
    )


def persist_grounding_dino_proposals(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    image_id: str,
    runtime_path: Path,
    device: str,
    task: str,
    detections: list[dict[str, Any]],
    prompt_labels: list[str],
    confidence_threshold: float,
    text_threshold: float,
) -> list[str]:
    project = _project(session, project_id)
    image = _image(session, project_id, image_id)
    spec = OPTIONAL_MODEL_SPECS["grounding_dino"]

    normalized: list[tuple[str, float, float, float, float, float, LabelClass | None]] = []
    for raw in detections:
        label = str(raw.get("label") or "").strip() or "open-vocabulary detection"
        confidence = float(raw.get("confidence", 0.0))
        box = raw.get("box")
        if not isinstance(box, dict):
            raise ValidationError("Grounding DINO result is missing a bounding box")
        try:
            x_min = float(box["x_min"])
            y_min = float(box["y_min"])
            x_max = float(box["x_max"])
            y_max = float(box["y_max"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Grounding DINO returned invalid box coordinates") from exc
        if x_max <= x_min or y_max <= y_min:
            raise ValidationError("Grounding DINO returned a non-positive bounding box")
        if x_min < 0 or y_min < 0 or x_max > image.width_px or y_max > image.height_px:
            raise ValidationError("Grounding DINO returned a box outside the source image")
        matched_class = _active_class_for_label(
            session,
            project_id=project_id,
            label=label,
        )
        normalized.append((label, confidence, x_min, y_min, x_max, y_max, matched_class))

    model = _ensure_catalog_proxy_registration(
        session,
        settings,
        project=project,
        provider_id="grounding_dino",
        runtime_path=runtime_path,
    )
    job = _new_inference_job(
        session,
        project_id=project_id,
        model_id=model.id,
        provider_id="grounding_dino",
        task=task,
        image_id=image_id,
        device=device,
        prompt_fields={
            "text_prompts": prompt_labels,
            "confidence": confidence_threshold,
            "text_threshold": text_threshold,
        },
    )

    proposals: list[PredictionProposal] = []
    for label, confidence, x_min, y_min, x_max, y_max, matched_class in normalized:
        proposal = PredictionProposal(
            project_id=project_id,
            image_id=image.id,
            model_id=model.id,
            inference_job_id=job.id,
            model_checksum=spec.weight_sha256 or model.sha256,
            label_class_id=matched_class.id if matched_class else None,
            predicted_label=label,
            predicted_index=matched_class.class_index if matched_class else None,
            confidence=confidence,
            geometry_kind="bounding_box",
            polygon_json=None,
            mask_path=None,
            mask_content_sha256=None,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            review_status="pending",
            inference_settings_json={
                "device": device,
                "task": task,
                "confidence_threshold": confidence_threshold,
                "text_threshold": text_threshold,
                "prompt_labels": prompt_labels,
            },
            provenance_json={
                "source": "advanced_provider",
                "provider_id": "grounding_dino",
                "catalog_id": _PROVIDER_CATALOG_IDS["grounding_dino"],
                "repo_id": spec.repo_id,
                "model_revision": spec.revision,
                "checkpoint_sha256": spec.weight_sha256,
                "project_proxy_model_id": model.id,
                "prompt_labels": prompt_labels,
                "proposal_geometry": "bounding_box",
                "requires_researcher_review": True,
            },
        )
        session.add(proposal)
        proposals.append(proposal)

    session.flush()
    proposal_ids = [item.id for item in proposals]
    _complete_job(job, proposal_ids)
    session.commit()
    return proposal_ids


def _store_mask(
    settings: Settings,
    *,
    project: Project,
    image: ImageAsset,
    proposal_id: str,
    mask_png_base64: str,
) -> tuple[str, str]:
    try:
        payload = base64.b64decode(mask_png_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("SAM 2 returned invalid base64 mask content") from exc
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            mask = source.convert("L")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("SAM 2 returned an unreadable mask image") from exc
    if mask.size != (image.width_px, image.height_px):
        raise ValidationError("SAM 2 mask dimensions do not match the source image")
    binary = mask.point(lambda value: 255 if value > 0 else 0)
    if binary.getbbox() is None:
        raise ValidationError("SAM 2 returned an empty mask")

    relative_dir = f"{project.storage_root}/prediction-masks/{proposal_id[:2]}"
    output_root = resolve_managed_project_path(settings, relative_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{proposal_id}.png"
    temporary = output_root / f".{proposal_id}.tmp"
    try:
        binary.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    relative_path = destination.relative_to(settings.resolved_data_dir).as_posix()
    return relative_path, _sha256_bytes(destination.read_bytes())


def persist_sam2_proposal(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    image_id: str,
    runtime_path: Path,
    device: str,
    mask_png_base64: str,
    score: float,
    box: dict[str, float],
    prompt_fields: dict[str, Any],
    source_repo_id: str | None = None,
    source_revision: str | None = None,
    source_checksum: str | None = None,
    source_variant: str | None = None,
) -> str:
    project = _project(session, project_id)
    image = _image(session, project_id, image_id)
    spec = OPTIONAL_MODEL_SPECS["sam2"]
    resolved_repo = source_repo_id or spec.repo_id
    resolved_revision = source_revision or spec.revision
    resolved_checksum = source_checksum or spec.weight_sha256

    try:
        x_min = float(box["x_min"])
        y_min = float(box["y_min"])
        x_max = float(box["x_max"])
        y_max = float(box["y_max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("SAM 2 returned invalid proposal bounds") from exc
    if x_max <= x_min or y_max <= y_min:
        raise ValidationError("SAM 2 returned a non-positive proposal box")
    if x_min < 0 or y_min < 0 or x_max > image.width_px or y_max > image.height_px:
        raise ValidationError("SAM 2 proposal bounds are outside the source image")

    label_class: LabelClass | None = None
    requested_class_id = prompt_fields.get("label_class_id")
    if requested_class_id:
        label_class = session.get(LabelClass, str(requested_class_id))
        if label_class is None or label_class.project_id != project_id or not label_class.is_active:
            raise ValidationError("Selected SAM 2 proposal class is not active in this project")

    proposal_id = str(uuid4())
    mask_path, mask_sha256 = _store_mask(
        settings,
        project=project,
        image=image,
        proposal_id=proposal_id,
        mask_png_base64=mask_png_base64,
    )
    model = _ensure_catalog_proxy_registration(
        session,
        settings,
        project=project,
        provider_id="sam2",
        runtime_path=runtime_path,
        source_repo_id=resolved_repo,
        source_revision=resolved_revision,
        source_checksum=resolved_checksum,
        source_variant=source_variant,
    )
    job = _new_inference_job(
        session,
        project_id=project_id,
        model_id=model.id,
        provider_id="sam2",
        task="assist_segmentation",
        image_id=image_id,
        device=device,
        prompt_fields=prompt_fields,
    )

    prompt_kind = "box" if prompt_fields.get("box") is not None else "points"
    proposal = PredictionProposal(
        id=proposal_id,
        project_id=project_id,
        image_id=image.id,
        model_id=model.id,
        inference_job_id=job.id,
        model_checksum=resolved_checksum or model.sha256,
        label_class_id=label_class.id if label_class else None,
        predicted_label=label_class.name if label_class else "SAM 2 mask",
        predicted_index=label_class.class_index if label_class else None,
        confidence=float(score),
        geometry_kind="raster_mask",
        polygon_json=None,
        mask_path=mask_path,
        mask_content_sha256=mask_sha256,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        review_status="pending",
        inference_settings_json={
            "device": device,
            "task": "assist_segmentation",
            "prompt_kind": prompt_kind,
            "prompt_fields": prompt_fields,
        },
        provenance_json={
            "source": "advanced_provider",
            "provider_id": "sam2",
            "catalog_id": _PROVIDER_CATALOG_IDS["sam2"],
            "repo_id": resolved_repo,
            "model_revision": resolved_revision,
            "model_variant": source_variant or "small",
            "checkpoint_sha256": resolved_checksum,
            "project_proxy_model_id": model.id,
            "proposal_geometry": "raster_mask",
            "prompt_kind": prompt_kind,
            "requires_researcher_review": True,
        },
    )
    session.add(proposal)
    session.flush()
    _complete_job(job, [proposal.id])
    session.commit()
    return proposal.id
