"""Workflow integration for multi-model segmentation consensus."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    WorkflowArtifact,
    WorkflowRun,
)
from reefvision.jobs import inference as inference_runtime
from reefvision.jobs import workflow_runs as workflow_runtime
from reefvision.ml import segmentation as segmentation_runtime
from reefvision.ml.sam3_sidecar import Sam3SidecarSegmentationProvider
from reefvision.services.independent_segmentation_pipeline import (
    run_independent_segmentation_pipeline,
)
from reefvision.services.mask_consensus import MaskAggregation
from reefvision.services.multi_model_auto_labeling import (
    apply_multi_model_mask_consensus,
)

_ORIGINAL_MODEL_INFERENCE = workflow_runtime._model_inference
_ORIGINAL_PROCESS_INFERENCE = workflow_runtime.process_inference_job
_ORIGINAL_SEGMENTATION_PROVIDER_FACTORY = segmentation_runtime.segmentation_provider_for_name


def _segmentation_provider_for_name(
    provider_name: str,
) -> segmentation_runtime.SegmentationProvider:
    if provider_name.strip().casefold() == "sam3_sidecar":
        return Sam3SidecarSegmentationProvider()
    return _ORIGINAL_SEGMENTATION_PROVIDER_FACTORY(provider_name)


def _workflow_inference_request_compatibility(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Normalize legacy Workflow inference keys before invoking the main worker."""

    with factory() as session:
        job = session.get(Job, job_id)
        if job is not None and job.job_type == "inference" and job.status == "queued":
            request = dict(job.request_json or {})
            changed = False
            if "confidence_threshold" not in request:
                request["confidence_threshold"] = float(
                    request.get("confidence", settings.inference_default_confidence)
                )
                changed = True
            if "iou_threshold" not in request:
                request["iou_threshold"] = settings.inference_default_iou
                changed = True
            if changed:
                job.request_json = request
                session.commit()
    return _ORIGINAL_PROCESS_INFERENCE(settings, factory, job_id)


def _require_primary_provider(
    factory: sessionmaker[Session],
    *,
    model_id: str,
    required_provider: str,
) -> None:
    with factory() as session:
        model = session.get(ModelRegistration, model_id)
        if model is None:
            raise RuntimeError("Consensus segmenter model disappeared before voting")
        if model.provider_name.strip().casefold() != required_provider.strip().casefold():
            raise RuntimeError(
                "This consensus Workflow requires primary provider "
                f"{required_provider!r}, but the selected model uses {model.provider_name!r}"
            )


def _synchronize_promoted_vote_counts(
    factory: sessionmaker[Session],
    result_payload: dict[str, Any],
) -> None:
    """Persist the same confidence-qualified vote count used for quorum."""

    candidates = result_payload.get("candidates")
    if not isinstance(candidates, list):
        return
    with factory() as session:
        changed = False
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            annotation_id = candidate.get("mask_annotation_id")
            proposal_id = candidate.get("proposal_id")
            accepted_vote_count = candidate.get("accepted_vote_count")
            if not isinstance(annotation_id, str) or not isinstance(accepted_vote_count, int):
                continue
            annotation = session.get(MaskAnnotation, annotation_id)
            if annotation is not None:
                annotation.provenance_json = {
                    **dict(annotation.provenance_json or {}),
                    "accepted_vote_count": accepted_vote_count,
                }
                changed = True
            if isinstance(proposal_id, str):
                proposal = session.get(PredictionProposal, proposal_id)
                if proposal is not None:
                    proposal_provenance = dict(proposal.provenance_json or {})
                    consensus = dict(proposal_provenance.get("workflow_consensus") or {})
                    consensus["accepted_vote_count"] = accepted_vote_count
                    proposal.provenance_json = {
                        **proposal_provenance,
                        "workflow_consensus": consensus,
                    }
                    changed = True
        if changed:
            session.commit()


def _independent_consensus(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    payload: dict[str, Any],
    raw_consensus: dict[str, Any],
) -> dict[str, Any]:
    if not bool(raw_consensus.get("allow_remote_review", False)):
        raise RuntimeError(
            "Independent mask generation requires allow_remote_review=true in the node"
        )
    sam2_model_id = str(raw_consensus.get("sam2_model_id", "")).strip()
    label_class_id = str(raw_consensus.get("label_class_id", "")).strip()
    prompt = str(raw_consensus.get("prompt", "")).strip()
    predicted_label = str(raw_consensus.get("predicted_label", prompt)).strip()
    primary_model_id = str(payload.get("model_id", "")).strip()
    primary_job_id = str(payload.get("child_job_id", "")).strip()
    if not all(
        (
            sam2_model_id,
            label_class_id,
            prompt,
            predicted_label,
            primary_model_id,
            primary_job_id,
        )
    ):
        raise RuntimeError(
            "Independent consensus requires sam2_model_id, label_class_id, prompt, "
            "predicted_label, and primary inference provenance"
        )
    aggregation_value = str(raw_consensus.get("aggregation", "pixel_majority"))
    if aggregation_value not in {
        "intersection",
        "pixel_majority",
        "union",
        "best_confidence",
    }:
        raise RuntimeError("Independent consensus aggregation is unsupported")
    image_ids = [str(value) for value in payload.get("image_ids", []) if isinstance(value, str)]
    prediction_ids = [
        str(value) for value in payload.get("prediction_ids", []) if isinstance(value, str)
    ]
    result = run_independent_segmentation_pipeline(
        settings,
        factory,
        image_ids=image_ids,
        primary_prediction_ids=prediction_ids,
        primary_model_id=primary_model_id,
        primary_inference_job_id=primary_job_id,
        sam2_model_id=sam2_model_id,
        label_class_id=label_class_id,
        predicted_label=predicted_label,
        concept_prompt=prompt,
        workflow_run_id=run.id,
        workflow_node_id=run.current_node_id or "segmenter",
        required_votes=int(raw_consensus.get("required_votes", 2)),
        iou_threshold=float(raw_consensus.get("iou_threshold", 0.3)),
        aggregation=cast(MaskAggregation, aggregation_value),
        minimum_vlm_confidence=float(raw_consensus.get("minimum_vlm_confidence", 0.25)),
        device=str(raw_consensus.get("sam2_device", "auto")),
        openai_model=str(raw_consensus.get("openai_model", "gpt-5-mini")),
        gemini_model=str(raw_consensus.get("gemini_model", "gemini-2.5-flash")),
        auto_accept=bool(raw_consensus.get("auto_accept", False)),
        fail_closed=bool(raw_consensus.get("fail_closed", True)),
    )
    result_payload = result.as_payload()
    consensus_prediction_ids = [
        str(proposal_id) for image in result.images for proposal_id in image.proposal_ids
    ]
    accepted_mask_ids = [
        str(annotation_id)
        for image in result.images
        for annotation_id in image.accepted_mask_annotation_ids
    ]
    return {
        **payload,
        "source_prediction_ids": prediction_ids,
        "prediction_ids": consensus_prediction_ids,
        "mask_annotation_ids": accepted_mask_ids,
        "consensus": result_payload,
        "auto_labeling_mode": "independent_masks_two_of_three",
    }


def _consensus_aware_model_inference(
    settings: Settings,
    factory: sessionmaker[Session],
    run: WorkflowRun,
    node_type: str,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runtime.ArtifactOutputs:
    outputs = _ORIGINAL_MODEL_INFERENCE(
        settings,
        factory,
        run,
        node_type,
        configuration,
        inputs,
    )
    raw_consensus = configuration.get("multi_model_consensus")
    if (
        node_type != "segmenter"
        or not isinstance(raw_consensus, dict)
        or not bool(raw_consensus.get("enabled", False))
    ):
        return outputs

    mask_output = outputs.get("masks")
    if mask_output is None:
        raise RuntimeError("Consensus-enabled segmenter did not produce a masks artifact")
    payload = dict(mask_output[1])
    model_id = str(payload.get("model_id", ""))
    required_provider = str(raw_consensus.get("required_primary_provider", "")).strip()
    if required_provider:
        _require_primary_provider(
            factory,
            model_id=model_id,
            required_provider=required_provider,
        )

    mode = str(raw_consensus.get("mode", "semantic_voters")).strip().casefold()
    if mode == "independent_masks":
        enhanced = _independent_consensus(
            settings,
            factory,
            run,
            payload,
            dict(raw_consensus),
        )
    elif mode == "semantic_voters":
        prediction_ids = [
            str(value) for value in payload.get("prediction_ids", []) if isinstance(value, str)
        ]
        result = apply_multi_model_mask_consensus(
            settings,
            factory,
            prediction_ids=prediction_ids,
            consensus_configuration=dict(raw_consensus),
            workflow_run_id=run.id,
            workflow_node_id=run.current_node_id or "segmenter",
        )
        result_payload = result.as_payload()
        _synchronize_promoted_vote_counts(factory, result_payload)
        accepted_mask_ids = [
            str(candidate["mask_annotation_id"])
            for candidate in result_payload["candidates"]
            if candidate.get("mask_annotation_id")
        ]
        enhanced = {
            **payload,
            "mask_annotation_ids": accepted_mask_ids,
            "consensus": result_payload,
            "auto_labeling_mode": "semantic_review_two_of_three",
        }
    else:
        raise RuntimeError(f"Unsupported multi-model consensus mode: {mode}")

    if len(mask_output) == 4:
        return {
            "masks": (
                mask_output[0],
                enhanced,
                mask_output[2],
                mask_output[3],
            )
        }
    return {"masks": (mask_output[0], enhanced)}


def install_consensus_workflow_runtime() -> None:
    """Install stable wrappers around the existing Workflow inference handlers."""

    segmentation_runtime.segmentation_provider_for_name = _segmentation_provider_for_name
    inference_runtime.segmentation_provider_for_name = _segmentation_provider_for_name
    if workflow_runtime.process_inference_job is not _workflow_inference_request_compatibility:
        workflow_runtime.process_inference_job = _workflow_inference_request_compatibility
    if workflow_runtime._model_inference is not _consensus_aware_model_inference:
        workflow_runtime._model_inference = _consensus_aware_model_inference


install_consensus_workflow_runtime()
process_workflow_run_job = workflow_runtime.process_workflow_run_job
