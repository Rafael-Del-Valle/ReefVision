"""Resolve reviewed segmentation proposals before scientific measurement.

A Segmenter artifact may be cached while proposal review happens later. Measurement therefore
resolves proposal state from the database at execution time. Pending proposals fail closed;
accepted proposals contribute only their accepted mask annotations; rejected proposals are
explicitly omitted. This prevents measurements from silently falling back to unrelated masks.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import PredictionProposal, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs
from reefvision.jobs.workflow_cache_runtime import install_workflow_cache_runtime
from reefvision.jobs.workflow_segmentation_provider_runtime import (
    install_segmentation_provider_runtime,
)

install_workflow_cache_runtime()
install_segmentation_provider_runtime()

_ORIGINAL_MEASUREMENT_SNAPSHOT = workflow_runs._measurement_snapshot
_REJECTED_STATES = {"rejected", "dismissed"}


def _segmentation_prediction_ids(inputs: list[WorkflowArtifact]) -> list[str]:
    proposal_ids: list[str] = []
    for artifact in inputs:
        if artifact.artifact_type != "masks":
            continue
        payload = workflow_runs._artifact_payload(artifact)
        raw = payload.get("prediction_ids")
        if isinstance(raw, list):
            proposal_ids.extend(str(value) for value in raw)
    return list(dict.fromkeys(proposal_ids))


def _input_mask_ids(inputs: list[WorkflowArtifact]) -> list[str]:
    mask_ids: list[str] = []
    for artifact in inputs:
        payload = workflow_runs._artifact_payload(artifact)
        for key in ("mask_annotation_ids", "mask_ids"):
            raw = payload.get(key)
            if isinstance(raw, list):
                mask_ids.extend(str(value) for value in raw)
    return list(dict.fromkeys(mask_ids))


def _review_summary(proposals: list[PredictionProposal]) -> dict[str, Any]:
    accepted = [
        proposal
        for proposal in proposals
        if proposal.accepted_mask_annotation_id is not None
    ]
    rejected = [
        proposal
        for proposal in proposals
        if proposal.review_status.strip().casefold() in _REJECTED_STATES
    ]
    unresolved = [
        proposal
        for proposal in proposals
        if proposal.accepted_mask_annotation_id is None
        and proposal.review_status.strip().casefold() not in _REJECTED_STATES
    ]
    return {
        "proposal_count": len(proposals),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "unresolved_count": len(unresolved),
        "accepted_mask_annotation_ids": [
            str(proposal.accepted_mask_annotation_id) for proposal in accepted
        ],
        "rejected_prediction_ids": [proposal.id for proposal in rejected],
        "unresolved_prediction_ids": [proposal.id for proposal in unresolved],
    }


def _with_review_provenance(
    outputs: workflow_runs.ArtifactOutputs,
    summary: dict[str, Any],
) -> workflow_runs.ArtifactOutputs:
    output = outputs.get("measurements")
    if output is None:
        return outputs
    artifact_type, raw_payload = output[:2]
    payload = dict(raw_payload)
    payload["segmentation_review"] = {
        **summary,
        "review_required": True,
        "review_resolved": True,
        "review_before_measurement": True,
    }
    if len(output) == 4:
        return {
            "measurements": (
                artifact_type,
                payload,
                output[2],
                output[3],
            )
        }
    return {"measurements": (artifact_type, payload)}


def _review_aware_measurement(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    configured_raw = configuration.get("mask_annotation_ids")
    configured_mask_ids = (
        [str(value) for value in configured_raw]
        if isinstance(configured_raw, list)
        else []
    )
    direct_mask_ids = _input_mask_ids(inputs)
    proposal_ids = _segmentation_prediction_ids(inputs)

    # Explicit or already-accepted mask artifacts are authoritative. Consensus workflows
    # populate mask_annotation_ids themselves and therefore bypass proposal review lookup.
    if configured_mask_ids or direct_mask_ids or not proposal_ids:
        return _ORIGINAL_MEASUREMENT_SNAPSHOT(factory, run, configuration, inputs)

    with factory() as session:
        proposals = list(
            session.scalars(
                select(PredictionProposal)
                .where(
                    PredictionProposal.project_id == run.project_id,
                    PredictionProposal.id.in_(proposal_ids),
                )
                .order_by(PredictionProposal.image_id, PredictionProposal.id)
            )
        )
    if len(proposals) != len(proposal_ids):
        raise RuntimeError("One or more segmentation proposals disappeared before review resolution")
    summary = _review_summary(proposals)
    if int(summary["unresolved_count"]) > 0:
        raise RuntimeError(
            "Segmentation review required before measurement: "
            f"{summary['unresolved_count']} of {summary['proposal_count']} proposal(s) "
            "still require accept/reject review. Review the mask proposals, then rerun the "
            "workflow; cached segmentation artifacts will resolve the accepted masks."
        )

    accepted_mask_ids = [str(value) for value in summary["accepted_mask_annotation_ids"]]
    if not accepted_mask_ids:
        payloads = [workflow_runs._artifact_payload(item) for item in inputs]
        image_ids = workflow_runs._list_values(payloads, "image_ids")
        return {
            "measurements": (
                "measurements",
                {
                    "image_ids": image_ids,
                    "mask_annotation_ids": [],
                    "measurement_count": 0,
                    "measurements": [],
                    "segmentation_review": {
                        **summary,
                        "review_required": True,
                        "review_resolved": True,
                        "review_before_measurement": True,
                    },
                },
            )
        }

    resolved_configuration = {
        **configuration,
        "mask_annotation_ids": accepted_mask_ids,
    }
    outputs = _ORIGINAL_MEASUREMENT_SNAPSHOT(
        factory,
        run,
        resolved_configuration,
        inputs,
    )
    return _with_review_provenance(outputs, summary)


workflow_runs._measurement_snapshot = _review_aware_measurement
