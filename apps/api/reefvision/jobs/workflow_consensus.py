"""Workflow integration for multi-model segmentation consensus."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, WorkflowArtifact, WorkflowRun
from reefvision.jobs import inference as inference_runtime
from reefvision.jobs import workflow_runs as workflow_runtime
from reefvision.ml import segmentation as segmentation_runtime
from reefvision.ml.sam3_sidecar import Sam3SidecarSegmentationProvider
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
    prediction_ids = [
        str(value)
        for value in payload.get("prediction_ids", [])
        if isinstance(value, str)
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
    accepted_mask_ids = [
        str(candidate["mask_annotation_id"])
        for candidate in result_payload["candidates"]
        if candidate.get("mask_annotation_id")
    ]
    enhanced = {
        **payload,
        "mask_annotation_ids": accepted_mask_ids,
        "consensus": result_payload,
        "auto_labeling_mode": "multi_model_two_of_three",
    }
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
