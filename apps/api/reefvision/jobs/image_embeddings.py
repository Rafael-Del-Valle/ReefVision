"""Restart-safe, batched automatic image-embedding generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ImageEmbedding, Job
from reefvision.ml.image_embedding_runtime import (
    ULTRALYTICS_EMBEDDING_PREPROCESSING_VERSION,
    UltralyticsBackboneEmbeddingProvider,
    color_texture_embedding,
    transformers_embedding,
)
from reefvision.ml.provider_verification import sha256_file
from reefvision.services.image_embeddings import embedding_identity_key
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


def _crop_tuple(crop: object) -> tuple[float, float, float, float] | None:
    if not isinstance(crop, dict):
        return None
    try:
        return (
            float(crop["x_min"]),
            float(crop["y_min"]),
            float(crop["x_max"]),
            float(crop["y_max"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Embedding job contains an invalid crop") from exc


def _generate_fixture_or_transformer(
    path: Path,
    crop: tuple[float, float, float, float] | None,
    *,
    provider_id: str,
    model_id: str,
    device: str,
    local_files_only: bool,
) -> tuple[list[float], dict[str, Any]]:
    with Image.open(path) as source:
        source.load()
        image = source.convert("RGB")
        if crop is not None:
            image = image.crop(crop)
    if provider_id == "color_texture_v1":
        vector, metadata = color_texture_embedding(image)
    elif provider_id == "transformers_vision":
        vector, metadata = transformers_embedding(
            image,
            model_id=model_id,
            device=device,
            local_files_only=local_files_only,
        )
    else:
        raise ValueError("Unsupported image-embedding provider")
    metadata.update(
        {
            "provider_id": provider_id,
            "model_id": model_id,
            "source_image_sha256": sha256_file(path),
            "crop": list(crop) if crop is not None else None,
            "normalization": "l2",
        }
    )
    return vector, metadata


def _cancelled(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    completed: int,
    skipped: int,
    failures: list[dict[str, str]],
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return True
        if job.status != "cancel_requested":
            return False
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
        job.result_json = {
            "stage": "cancelled",
            "completed": completed,
            "skipped": skipped,
            "failures": failures,
        }
        session.commit()
        return True


def process_image_embedding_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "image_embeddings" or job.status != "queued":
            return False
        request = dict(job.request_json)
        raw_work_items = request.get("resolved_work_items")
        if isinstance(raw_work_items, list):
            work_items = [dict(item) for item in raw_work_items if isinstance(item, dict)]
        else:
            work_items = [
                {"image_id": str(value), "source_kind": "image", "crop": None}
                for value in request.get("resolved_image_ids", [])
            ]
        job.status = "running"
        job.started_at = job.started_at or datetime.now(UTC)
        job.heartbeat_at = datetime.now(UTC)
        job.error_message = None
        job.progress_total = len(work_items)
        job.result_json = {"stage": "embedding", "completed": 0}
        session.commit()

    completed = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    provider_id = str(request.get("provider_id", "ultralytics_backbone"))
    model_id = str(request.get("model_id", "ultralytics/yolo11/detect/n"))
    model_checksum_value = request.get("resolved_model_checksum") or request.get("model_checksum")
    model_checksum = str(model_checksum_value) if model_checksum_value else None
    model_version = str(request.get("resolved_model_version") or "unknown")
    preprocessing_version = str(
        request.get("resolved_preprocessing_version")
        or request.get("preprocessing_version")
        or ULTRALYTICS_EMBEDDING_PREPROCESSING_VERSION
    )
    replace_existing = bool(request.get("replace_existing", False))
    device = str(request.get("device", "auto"))
    local_files_only = bool(request.get("local_files_only", True))
    batch_size = max(1, min(64, int(request.get("batch_size", 8))))
    runner: UltralyticsBackboneEmbeddingProvider | None = None
    if provider_id == "ultralytics_backbone":
        checkpoint_value = request.get("resolved_checkpoint_path")
        if not isinstance(checkpoint_value, str) or not checkpoint_value or not model_checksum:
            raise RuntimeError("Embedding job is missing its verified local checkpoint identity")
        runner = UltralyticsBackboneEmbeddingProvider(
            model_id=model_id,
            model_version=model_version,
            checkpoint_path=Path(checkpoint_value),
            checkpoint_checksum=model_checksum,
        )
        runner.load(device)

    try:
        for start in range(0, len(work_items), batch_size):
            if _cancelled(
                factory,
                job_id,
                completed=completed,
                skipped=skipped,
                failures=failures,
            ):
                return True
            batch = work_items[start : start + batch_size]
            pending: list[
                tuple[
                    dict[str, object],
                    ImageAsset,
                    Path,
                    tuple[float, float, float, float] | None,
                    dict[str, float] | None,
                    str,
                ]
            ] = []
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                checkpoint_keys = {
                    str(value) for value in job.checkpoint_json.get("completed_embedding_keys", [])
                }
                for item in batch:
                    image_id = str(item.get("image_id") or "")
                    image = session.get(ImageAsset, image_id)
                    if image is None:
                        failures.append({"image_id": image_id, "error": "Image is missing"})
                        job.progress_current += 1
                        continue
                    crop_tuple = _crop_tuple(item.get("crop"))
                    crop_json = (
                        {
                            "x_min": crop_tuple[0],
                            "y_min": crop_tuple[1],
                            "x_max": crop_tuple[2],
                            "y_max": crop_tuple[3],
                        }
                        if crop_tuple is not None
                        else None
                    )
                    source_kind = "crop" if crop_tuple is not None else "image"
                    embedding_key = embedding_identity_key(
                        provider_id=provider_id,
                        model_id=model_id,
                        model_checksum=model_checksum,
                        model_version=model_version,
                        preprocessing_version=preprocessing_version,
                        source_kind=source_kind,
                        crop=crop_json,
                    )
                    checkpoint_token = f"{image.id}:{embedding_key}"
                    if checkpoint_token in checkpoint_keys:
                        skipped += 1
                        job.progress_current += 1
                        continue
                    existing = session.scalar(
                        select(ImageEmbedding).where(
                            ImageEmbedding.image_id == image.id,
                            ImageEmbedding.embedding_key == embedding_key,
                        )
                    )
                    if (
                        existing is not None
                        and existing.status == "ready"
                        and existing.source_image_sha256 == image.sha256
                        and not replace_existing
                    ):
                        skipped += 1
                        checkpoint_keys.add(checkpoint_token)
                        job.progress_current += 1
                        continue
                    image_path = resolve_managed_project_path(settings, image.managed_path)
                    if not image_path.is_file() or sha256_file(image_path) != image.sha256:
                        failures.append(
                            {
                                "image_id": image.id,
                                "error": "Managed original image checksum verification failed",
                            }
                        )
                        job.progress_current += 1
                        continue
                    pending.append((item, image, image_path, crop_tuple, crop_json, embedding_key))
                job.checkpoint_json = {
                    **job.checkpoint_json,
                    "completed_embedding_keys": sorted(checkpoint_keys),
                }
                job.result_json = {
                    "stage": "embedding",
                    "completed": completed,
                    "skipped": skipped,
                    "failures": failures,
                }
                session.commit()

            if not pending:
                continue
            try:
                if runner is not None:
                    generated = runner.embed_batch(
                        [(path, crop) for _item, _image, path, crop, _json, _key in pending]
                    )
                else:
                    generated = [
                        _generate_fixture_or_transformer(
                            path,
                            crop,
                            provider_id=provider_id,
                            model_id=model_id,
                            device=device,
                            local_files_only=local_files_only,
                        )
                        for _item, _image, path, crop, _json, _key in pending
                    ]
            except Exception as exc:
                generated = []
                failures.extend(
                    {"image_id": image.id, "error": str(exc)}
                    for _item, image, _path, _crop, _json, _key in pending
                )

            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                checkpoint_keys = {
                    str(value) for value in job.checkpoint_json.get("completed_embedding_keys", [])
                }
                for pending_item, generated_item in zip(pending, generated, strict=True):
                    _item, original_image, _path, _crop, crop_json, embedding_key = pending_item
                    vector, metadata = generated_item
                    image = session.get(ImageAsset, original_image.id)
                    if image is None:
                        raise RuntimeError("Embedding image disappeared during batch persistence")
                    embedding = session.scalar(
                        select(ImageEmbedding).where(
                            ImageEmbedding.image_id == image.id,
                            ImageEmbedding.embedding_key == embedding_key,
                        )
                    )
                    if embedding is None:
                        embedding = ImageEmbedding(
                            project_id=image.project_id,
                            image_id=image.id,
                            embedding_key=embedding_key,
                            provider_id=provider_id,
                            embedding_model_id=model_id,
                            model_version=model_version,
                            embedding_model_checksum=model_checksum,
                            preprocessing_version=preprocessing_version,
                            source_image_sha256=image.sha256,
                            source_kind="crop" if crop_json is not None else "image",
                            crop_json=crop_json,
                            normalization="l2",
                            status="ready",
                            dimension=len(vector),
                            vector_json=vector,
                            vector_sha256=canonical_json_sha256(vector),
                            source_json=metadata,
                        )
                        session.add(embedding)
                    else:
                        embedding.source_image_sha256 = image.sha256
                        embedding.status = "ready"
                        embedding.dimension = len(vector)
                        embedding.vector_json = vector
                        embedding.vector_sha256 = canonical_json_sha256(vector)
                        embedding.source_json = metadata
                    completed += 1
                    job.progress_current += 1
                    checkpoint_keys.add(f"{image.id}:{embedding_key}")
                # A failed batch still advances every attempted work item.
                if not generated:
                    job.progress_current += len(pending)
                job.checkpoint_json = {
                    **job.checkpoint_json,
                    "completed_embedding_keys": sorted(checkpoint_keys),
                    "last_batch_end": start + len(batch),
                }
                job.heartbeat_at = datetime.now(UTC)
                job.result_json = {
                    "stage": "embedding",
                    "completed": completed,
                    "skipped": skipped,
                    "failures": failures,
                }
                session.commit()
    finally:
        if runner is not None:
            runner.unload()

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return False
        job.status = "succeeded" if completed or skipped else "failed"
        job.error_message = (
            None if job.status == "succeeded" else "No image embeddings were generated"
        )
        job.completed_at = datetime.now(UTC)
        job.result_json = {
            "stage": "completed" if job.status == "succeeded" else "failed",
            "provider_id": provider_id,
            "embedding_model_id": model_id,
            "embedding_model_checksum": model_checksum,
            "model_version": model_version,
            "preprocessing_version": preprocessing_version,
            "completed": completed,
            "skipped": skipped,
            "failure_count": len(failures),
            "failures": failures,
        }
        session.commit()
    return True
