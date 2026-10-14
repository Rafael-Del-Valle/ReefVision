"""Persisted, cancellation-aware automatic SAM generation worker."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, MaskAnnotation, PredictionProposal, Project
from reefvision.domain.errors import ValidationError
from reefvision.ml.sam_image_proposals import (
    SAM_INFERENCE_LOCK,
    MaskCandidate,
    candidate_iou,
    generate_candidates,
)
from reefvision.schemas.sam_image_proposals import SamImageProposalsRequest
from reefvision.services.advanced_provider_proposals import _ensure_catalog_proxy_registration
from reefvision.services.sam2_install import sam2_status, variant_repo
from reefvision.storage.sam_image_proposals import (
    read_reference_mask,
    read_source,
    remove_candidates,
    store_candidate,
)


class GenerationCancelled(Exception):
    pass


def process_sam_image_proposals_job(
    settings: Settings, factory: sessionmaker[Session], job_id: str
) -> bool:
    started = time.monotonic()
    paths: list[str] = []
    with factory() as session:
        claim = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.job_type == "sam_image_proposals", Job.status == "queued")
            .values(status="running", started_at=datetime.now(UTC), error_message=None)
        )
        session.commit()
        if getattr(claim, "rowcount", 0) != 1:
            return False
        job = session.get(Job, job_id)
        assert job is not None
        project_id = job.project_id
        payload = job.request_json

    try:
        request = SamImageProposalsRequest.model_validate(payload)

        def checkpoint(stage: str, current: int, total: int) -> None:
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None or job.status != "running":
                    raise GenerationCancelled()
                if time.monotonic() - started > request.timeout_seconds:
                    raise ValidationError(
                        "SAM generation exceeded its time budget; reduce grid density"
                    )
                job.progress_current = current
                job.progress_total = total
                job.result_json = {
                    "stage": stage,
                    "image_id": str(request.image_id),
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                }
                session.commit()

        checkpoint("loading", 0, 1)
        installed = sam2_status(settings, request.variant)
        if not installed["ready"]:
            raise ValidationError(f"Choose/download SAM 2.1 in Model Hub. {installed['reason']}")
        with factory() as session:
            image = session.get(ImageAsset, str(request.image_id))
            if image is None or image.project_id != project_id:
                raise ValidationError("The SAM job image no longer exists in this project")
            managed_path = image.managed_path
        source = read_source(settings, managed_path)
        selected: list[MaskCandidate] = []
        while not SAM_INFERENCE_LOCK.acquire(timeout=0.25):
            checkpoint("waiting_for_runtime", 0, 1)
        try:
            for candidate in generate_candidates(
                source, str(installed["path"]), request, checkpoint
            ):
                # Deterministic score-ranked mask NMS, with bounded candidate memory.
                duplicates = [
                    item
                    for item in selected
                    if candidate_iou(candidate, item) >= request.proposal_iou_threshold
                ]
                if any(item.score >= candidate.score for item in duplicates):
                    continue
                selected = [item for item in selected if not any(item is old for old in duplicates)]
                selected.append(candidate)
                selected.sort(key=lambda item: item.score, reverse=True)
                del selected[request.max_candidates :]
        finally:
            SAM_INFERENCE_LOCK.release()
        checkpoint("filtering_verified_masks", 0, len(selected))

        with factory() as session:
            image = session.get(ImageAsset, str(request.image_id))
            project = session.get(Project, project_id)
            if image is None or project is None:
                raise ValidationError("SAM job project or image no longer exists")
            references = [
                (mask.mask_path, mask.polygon_json, request.verified_iou_threshold)
                for mask in session.scalars(
                    select(MaskAnnotation).where(
                        MaskAnnotation.image_id == image.id,
                        MaskAnnotation.deleted_at.is_(None),
                        MaskAnnotation.status == "verified",
                    )
                )
            ]
            references.extend(
                (proposal.mask_path, proposal.polygon_json, request.proposal_iou_threshold)
                for proposal in session.scalars(
                    select(PredictionProposal).where(
                        PredictionProposal.image_id == image.id,
                        PredictionProposal.review_status == "pending",
                        PredictionProposal.geometry_kind.in_(("raster_mask", "polygon")),
                    )
                )
            )
            # Decode one existing source mask at a time, preserving holes and touching objects.
            for index, (path, polygon, threshold) in enumerate(references):
                checkpoint("filtering_verified_masks", index, len(references))
                reference = MaskCandidate(
                    read_reference_mask(settings, path, polygon, source.size), 0, 0, 1, 1
                )
                selected = [item for item in selected if candidate_iou(item, reference) < threshold]
            checkpoint("persisting", 0, len(selected))
            # Claim finalization transactionally so cancellation cannot be overwritten.
            finalize = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="succeeded")
            )
            if getattr(finalize, "rowcount", 0) != 1:
                raise GenerationCancelled()
            model = _ensure_catalog_proxy_registration(
                session,
                settings,
                project=project,
                provider_id="sam2",
                runtime_path=Path(str(installed["path"])),
                source_repo_id=variant_repo(request.variant),
                source_revision=str(installed["revision"]),
                source_checksum=str(installed["weight_sha256"]),
                source_variant=request.variant,
            )
            ids: list[str] = []
            for candidate in selected:
                proposal_id = str(uuid4())
                path, checksum, bounds = store_candidate(
                    settings,
                    storage_root=project.storage_root,
                    image_id=image.id,
                    proposal_id=proposal_id,
                    mask=candidate.mask,
                    origin=(candidate.x, candidate.y),
                    size=source.size,
                )
                paths.append(path)
                session.add(
                    PredictionProposal(
                        id=proposal_id,
                        project_id=project.id,
                        image_id=image.id,
                        model_id=model.id,
                        inference_job_id=job_id,
                        model_checksum=str(installed["weight_sha256"]),
                        label_class_id=None,
                        predicted_label="Unclassified SAM object",
                        predicted_index=None,
                        confidence=candidate.score,
                        geometry_kind="raster_mask",
                        mask_path=path,
                        mask_content_sha256=checksum,
                        x_min=bounds[0],
                        y_min=bounds[1],
                        x_max=bounds[2],
                        y_max=bounds[3],
                        review_status="pending",
                        inference_settings_json=request.model_dump(mode="json"),
                        provenance_json={
                            "source": "sam_image_proposals",
                            "provider_id": "sam2",
                            "repo_id": variant_repo(request.variant),
                            "model_revision": installed["revision"],
                            "model_variant": request.variant,
                            "checkpoint_sha256": installed["weight_sha256"],
                            "run_id": job_id,
                            "training_dataset_id": None,
                            "class_agnostic": True,
                            "requires_researcher_review": True,
                            "stability": candidate.stability,
                            "point": candidate.point,
                            "tile_origin": [candidate.x, candidate.y],
                            "area_pixels": candidate.area,
                            "resolved_device": candidate.device,
                        },
                    )
                )
                ids.append(proposal_id)
            job = session.get(Job, job_id)
            assert job is not None
            job.completed_at = datetime.now(UTC)
            job.progress_current = job.progress_total
            job.result_json = {
                "stage": "completed",
                "image_id": image.id,
                "proposal_ids": ids,
                "proposal_count": len(ids),
                "class_agnostic": True,
                "review_status": "pending",
                "warnings": [
                    "Bounded SAM sampling can miss small objects and objects cut by tile edges; "
                    "all candidates require class assignment and human review."
                ],
            }
            session.commit()
        return True
    except Exception as exc:
        remove_candidates(settings, paths)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                cancelled = isinstance(exc, GenerationCancelled) or job.status == "cancel_requested"
                job.status = "cancelled" if cancelled else "failed"
                job.error_message = None if cancelled else str(exc)
                job.completed_at = datetime.now(UTC)
                job.result_json = {"stage": job.status, "proposal_ids": [], "proposal_count": 0}
                session.commit()
        return isinstance(exc, GenerationCancelled)
