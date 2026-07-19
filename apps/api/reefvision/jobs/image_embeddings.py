"""Background automatic image-embedding generation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ImageEmbedding, Job
from reefvision.ml.image_embedding_runtime import generate_image_embedding
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


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
        image_ids = [str(value) for value in request.get("resolved_image_ids", [])]
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.progress_current = 0
        job.progress_total = len(image_ids)
        job.result_json = {"stage": "embedding", "completed": 0}
        session.commit()

    completed = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    provider_id = str(request.get("provider_id", "color_texture_v1"))
    model_id = str(request.get("model_id", "reefvision-color-texture-v1"))
    model_checksum = request.get("model_checksum")
    replace_existing = bool(request.get("replace_existing", False))
    for image_id in image_ids:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            if job.status == "cancel_requested":
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
            image = session.get(ImageAsset, image_id)
            existing = session.scalar(
                select(ImageEmbedding).where(
                    ImageEmbedding.image_id == image_id,
                    ImageEmbedding.embedding_model_id == model_id,
                )
            )
            if image is None:
                failures.append({"image_id": image_id, "error": "Image is missing"})
                job.progress_current += 1
                session.commit()
                continue
            if existing is not None and not replace_existing:
                skipped += 1
                job.progress_current += 1
                job.result_json = {
                    "stage": "embedding",
                    "completed": completed,
                    "skipped": skipped,
                    "failures": failures,
                }
                session.commit()
                continue
            image_path = resolve_managed_project_path(settings, image.managed_path)

        try:
            vector, metadata = generate_image_embedding(
                image_path,
                provider_id=provider_id,
                model_id=model_id,
                device=str(request.get("device", "auto")),
                local_files_only=bool(request.get("local_files_only", True)),
            )
            checksum = canonical_json_sha256(vector)
            with factory() as session:
                image = session.get(ImageAsset, image_id)
                job = session.get(Job, job_id)
                if image is None or job is None:
                    raise RuntimeError("Embedding job records disappeared")
                embedding = session.scalar(
                    select(ImageEmbedding).where(
                        ImageEmbedding.image_id == image.id,
                        ImageEmbedding.embedding_model_id == model_id,
                    )
                )
                if embedding is None:
                    embedding = ImageEmbedding(
                        project_id=image.project_id,
                        image_id=image.id,
                        embedding_model_id=model_id,
                        embedding_model_checksum=(str(model_checksum) if model_checksum else None),
                        dimension=len(vector),
                        vector_json=vector,
                        vector_sha256=checksum,
                        source_json=metadata,
                    )
                    session.add(embedding)
                else:
                    embedding.embedding_model_checksum = (
                        str(model_checksum) if model_checksum else None
                    )
                    embedding.dimension = len(vector)
                    embedding.vector_json = vector
                    embedding.vector_sha256 = checksum
                    embedding.source_json = metadata
                completed += 1
                job.progress_current += 1
                job.result_json = {
                    "stage": "embedding",
                    "completed": completed,
                    "skipped": skipped,
                    "failures": failures,
                }
                session.commit()
        except Exception as exc:
            failures.append({"image_id": image_id, "error": str(exc)})
            with factory() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    job.progress_current += 1
                    job.result_json = {
                        "stage": "embedding",
                        "completed": completed,
                        "skipped": skipped,
                        "failures": failures,
                    }
                    session.commit()

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
            "embedding_model_id": model_id,
            "completed": completed,
            "skipped": skipped,
            "failure_count": len(failures),
            "failures": failures,
        }
        session.commit()
    return True
