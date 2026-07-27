"""Image-driven orchestration for three independent segmentation branches."""

from __future__ import annotations

from typing import cast

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    MaskAnnotation,
    MaskAnnotationEvent,
    ModelRegistration,
    PredictionProposal,
    Project,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.services.independent_segmentation_auto_labeling import (
    BoxMaskRefiner,
    GeminiBoxDetector,
    IndependentAutoLabelBatchResult,
    IndependentAutoLabelImageResult,
    OpenAIBoxDetector,
    SAM2BoxRefiner,
    VLMBoxDetector,
    _group_proposal,
    _source_png,
)
from reefvision.services.mask_consensus import (
    IndependentMaskCandidate,
    MaskAggregation,
    build_mask_consensus,
)
from reefvision.services.multi_model_auto_labeling import MaskVote, _promote, _proposal_mask
from reefvision.storage.masks import remove_prediction_mask_png
from reefvision.storage.projects import resolve_managed_project_path


def _record_independent_promotion(
    factory: sessionmaker[Session],
    *,
    annotation_id: str,
    proposal_id: str,
    aggregation: MaskAggregation,
    required_votes: int,
) -> None:
    """Correct the generic promotion label and append an auditable provenance event."""

    with factory() as session:
        annotation = session.get(MaskAnnotation, annotation_id)
        proposal = session.get(PredictionProposal, proposal_id)
        if annotation is None or proposal is None:
            raise ValidationError("Independent consensus promotion records are missing")
        before = mask_annotation_snapshot(annotation)
        proposal_provenance = dict(proposal.provenance_json or {})
        annotation.source_type = "workflow_independent_consensus"
        annotation.provenance_json = {
            **dict(annotation.provenance_json or {}),
            "consensus_method": "independent_mask_generation",
            "aggregation": aggregation,
            "required_votes": required_votes,
            "candidate_ids": list(proposal_provenance.get("candidate_ids") or []),
            "branch_ids": list(proposal_provenance.get("branch_ids") or []),
            "pairwise_mask_iou": dict(proposal_provenance.get("pairwise_mask_iou") or {}),
            "candidate_provenance": dict(proposal_provenance.get("candidate_provenance") or {}),
        }
        annotation.revision += 1
        session.add(
            MaskAnnotationEvent(
                mask_annotation_id=annotation.id,
                image_id=annotation.image_id,
                event_type="provenance_updated",
                before_json=before,
                after_json=mask_annotation_snapshot(annotation),
                actor="workflow_independent_consensus",
            )
        )
        session.commit()


def run_independent_segmentation_pipeline(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    image_ids: list[str],
    primary_prediction_ids: list[str],
    primary_model_id: str,
    primary_inference_job_id: str,
    sam2_model_id: str,
    label_class_id: str,
    predicted_label: str,
    concept_prompt: str,
    workflow_run_id: str,
    workflow_node_id: str,
    required_votes: int = 2,
    iou_threshold: float = 0.3,
    aggregation: MaskAggregation = "pixel_majority",
    minimum_vlm_confidence: float = 0.25,
    device: str = "auto",
    openai_model: str = "gpt-5-mini",
    gemini_model: str = "gemini-2.5-flash",
    auto_accept: bool = False,
    fail_closed: bool = True,
    detectors: list[VLMBoxDetector] | None = None,
    refiner: BoxMaskRefiner | None = None,
) -> IndependentAutoLabelBatchResult:
    """Evaluate every selected image, even when the primary segmenter found nothing."""

    if settings.safe_mode:
        raise ValidationError("Remote independent auto-labeling is disabled in safe mode")
    if not settings.allow_remote_vision:
        raise ValidationError(
            "Independent VLM auto-labeling requires REEFVISION_ALLOW_REMOTE_VISION=true"
        )
    if not concept_prompt.strip():
        raise ValidationError("Independent auto-labeling requires a concept prompt")
    unique_image_ids = list(dict.fromkeys(image_ids))
    if not unique_image_ids:
        raise ValidationError("Independent auto-labeling requires at least one input image")

    with factory() as session:
        primary_model = session.get(ModelRegistration, primary_model_id)
        sam2_model = session.get(ModelRegistration, sam2_model_id)
        if primary_model is None or sam2_model is None:
            raise ValidationError("Independent auto-labeling references a missing model")
        images = [session.get(ImageAsset, image_id) for image_id in unique_image_ids]
        if any(image is None for image in images):
            raise ValidationError("Independent auto-labeling references a missing image")
        resolved_images = [cast(ImageAsset, image) for image in images]
        project_ids = {image.project_id for image in resolved_images}
        if len(project_ids) != 1:
            raise ValidationError("Independent auto-labeling images must share one project")
        proposals = [
            proposal
            for proposal_id in dict.fromkeys(primary_prediction_ids)
            if (proposal := session.get(PredictionProposal, proposal_id)) is not None
        ]
        allowed_image_ids = set(unique_image_ids)
        if any(proposal.image_id not in allowed_image_ids for proposal in proposals):
            raise ValidationError("A primary proposal does not belong to the input image batch")
        if any(proposal.model_id != primary_model_id for proposal in proposals):
            raise ValidationError("Primary proposals must come from the selected primary model")

    configured_detectors = detectors or [
        GeminiBoxDetector(settings, gemini_model),
        OpenAIBoxDetector(settings, openai_model),
    ]
    if len({item.branch_id for item in configured_detectors}) != len(configured_detectors):
        raise ValidationError("Independent detector branch IDs must be unique")
    owned_refiner = refiner is None
    active_refiner = refiner or SAM2BoxRefiner(settings, sam2_model, device=device)
    image_results: list[IndependentAutoLabelImageResult] = []
    failed_images = 0
    try:
        for image_id in unique_image_ids:
            warnings: list[str] = []
            created_proposal_ids: list[str] = []
            accepted_ids: list[str] = []
            try:
                with factory() as session:
                    image = session.get(ImageAsset, image_id)
                    project = session.get(Project, image.project_id) if image is not None else None
                    if image is None or project is None:
                        raise ValidationError(
                            "Independent auto-labeling persistence context is missing"
                        )
                    image_path = resolve_managed_project_path(settings, image.managed_path)
                    primary_for_image = [item for item in proposals if item.image_id == image_id]
                    primary_candidates = [
                        IndependentMaskCandidate(
                            candidate_id=item.id,
                            branch_id="sam3",
                            image_id=image.id,
                            class_key=predicted_label,
                            confidence=float(item.confidence),
                            mask=np.asarray(
                                _proposal_mask(
                                    settings,
                                    proposal=item,
                                    project=project,
                                    image=image,
                                ),
                                dtype=np.uint8,
                            )
                            > 0,
                            provenance={
                                "source_prediction_id": item.id,
                                "source_model_id": item.model_id,
                                "source_model_checksum": item.model_checksum,
                                "source_inference_job_id": item.inference_job_id,
                                "source_predicted_label": item.predicted_label,
                            },
                        )
                        for item in primary_for_image
                    ]
                image_png, width, height = _source_png(image_path)
                detections = []
                for detector in configured_detectors:
                    try:
                        detections.extend(
                            detector.detect(
                                image_png=image_png,
                                width=width,
                                height=height,
                                concept_prompt=concept_prompt,
                                minimum_confidence=minimum_vlm_confidence,
                            )
                        )
                    except Exception as exc:
                        if not fail_closed:
                            raise
                        warnings.append(f"{detector.branch_id} failed: {exc}")
                refined = active_refiner.refine(
                    image_id=image_id,
                    image_path=image_path,
                    class_key=predicted_label,
                    detections=detections,
                )
                all_candidates = [*primary_candidates, *refined]
                consensus = build_mask_consensus(
                    all_candidates,
                    required_votes=required_votes,
                    iou_threshold=iou_threshold,
                    aggregation=aggregation,
                )
                warnings.extend(consensus.warnings)
                candidate_by_id = {item.candidate_id: item for item in all_candidates}
                staged_proposals: list[tuple[str, str]] = []
                project_storage_root = ""
                try:
                    with factory() as session:
                        image = session.get(ImageAsset, image_id)
                        project = (
                            session.get(Project, image.project_id) if image is not None else None
                        )
                        model = session.get(ModelRegistration, primary_model_id)
                        if image is None or project is None or model is None:
                            raise ValidationError(
                                "Independent consensus persistence context is missing"
                            )
                        project_storage_root = project.storage_root
                        for group in consensus.groups:
                            proposal = _group_proposal(
                                settings,
                                session,
                                project=project,
                                image=image,
                                group=group,
                                source_model=model,
                                inference_job_id=primary_inference_job_id,
                                label_class_id=label_class_id,
                                predicted_label=predicted_label,
                                workflow_run_id=workflow_run_id,
                                workflow_node_id=workflow_node_id,
                                source_candidates=candidate_by_id,
                            )
                            if proposal.mask_path is None:
                                raise ValidationError(
                                    "Independent consensus proposal is missing its mask path"
                                )
                            staged_proposals.append((proposal.id, proposal.mask_path))
                            created_proposal_ids.append(proposal.id)
                        session.commit()
                except Exception:
                    if project_storage_root:
                        for proposal_id, relative_path in staged_proposals:
                            remove_prediction_mask_png(
                                settings,
                                project_storage_root=project_storage_root,
                                proposal_id=proposal_id,
                                relative_path=relative_path,
                            )
                    raise
                if auto_accept:
                    for proposal_id, group in zip(
                        created_proposal_ids,
                        consensus.groups,
                        strict=True,
                    ):
                        votes = [
                            MaskVote(
                                voter=branch_id,
                                model=branch_id,
                                accepted=True,
                                confidence=group.confidence,
                                reason=(
                                    "Independent branch mask participated in "
                                    "class-aware pixel consensus."
                                ),
                            )
                            for branch_id in group.branch_ids
                        ]
                        annotation_id = _promote(
                            settings,
                            factory,
                            proposal_id=proposal_id,
                            votes=votes,
                            required_votes=required_votes,
                            concept_prompt=concept_prompt,
                            workflow_run_id=workflow_run_id,
                            workflow_node_id=workflow_node_id,
                        )
                        _record_independent_promotion(
                            factory,
                            annotation_id=annotation_id,
                            proposal_id=proposal_id,
                            aggregation=aggregation,
                            required_votes=required_votes,
                        )
                        accepted_ids.append(annotation_id)
                image_results.append(
                    IndependentAutoLabelImageResult(
                        image_id=image_id,
                        primary_candidate_count=len(primary_candidates),
                        vlm_detection_count=len(detections),
                        refined_mask_count=len(refined),
                        consensus_count=len(consensus.groups),
                        proposal_ids=tuple(created_proposal_ids),
                        accepted_mask_annotation_ids=tuple(accepted_ids),
                        warnings=tuple(warnings),
                    )
                )
            except Exception as exc:
                failed_images += 1
                if not fail_closed:
                    raise
                image_results.append(
                    IndependentAutoLabelImageResult(
                        image_id=image_id,
                        primary_candidate_count=0,
                        vlm_detection_count=0,
                        refined_mask_count=0,
                        consensus_count=0,
                        proposal_ids=(),
                        accepted_mask_annotation_ids=(),
                        warnings=(str(exc),),
                    )
                )
    finally:
        if owned_refiner:
            active_refiner.close()

    return IndependentAutoLabelBatchResult(
        image_count=len(image_results),
        consensus_count=sum(item.consensus_count for item in image_results),
        proposal_count=sum(len(item.proposal_ids) for item in image_results),
        accepted_count=sum(len(item.accepted_mask_annotation_ids) for item in image_results),
        failed_image_count=failed_images,
        images=tuple(image_results),
    )
