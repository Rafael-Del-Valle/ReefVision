"""Workflow Builder adapter for persistent, human-reviewable QC queues.

Queues rank review effort; they never establish verified biological truth.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun, WorkflowRun
from reefvision.domain.errors import ValidationError
from reefvision.schemas.review_queues import ReviewQueueCreateRequest
from reefvision.services.review_queues import ReviewQueueService
from reefvision.services.workflow_review_queue_integrity import (
    validate_saved_queue_snapshot,
)
from reefvision.storage.datasets import canonical_json_sha256


def create_review_queue_workflow_artifact(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    """Generate once per workflow node, reusing persisted output on interrupted retries."""
    sources = inputs.get("project", [])
    if len(sources) != 1 or sources[0].data_type != "project_reference":
        raise ValidationError("QC Review Queue requires exactly one project reference")
    # A saved Workflow Builder retry must not trust a source reference whose
    # persisted JSON was altered after its checksum was recorded. Verify this
    # before queue creation or reuse; no research data is rewritten on failure.
    source_payload = sources[0].payload_json
    if not isinstance(source_payload, dict) or sources[0].payload_sha256 != canonical_json_sha256(
        source_payload
    ):
        raise ValidationError("QC Review Queue source artifact failed integrity validation")
    if source_payload.get("project_id") != project_id:
        raise ValidationError("QC Review Queue received a foreign project reference")

    run_id = str(parameters.get("__workflow_run_id") or "")
    node_run_id = str(parameters.get("__workflow_node_run_id") or "")
    run = session.get(WorkflowRun, run_id) if run_id else None
    node = session.get(WorkflowNodeRun, node_run_id) if node_run_id else None
    if (
        run is None
        or run.project_id != project_id
        or node is None
        or node.workflow_run_id != run_id
        or node.node_type != "qc_review_queue"
        or sources[0].workflow_run_id != run_id
    ):
        raise ValidationError("QC Review Queue requires valid persisted workflow provenance")

    # A matching project ID and payload digest are not sufficient provenance:
    # bind the input to its completed project-source node, output port and
    # the producer's persisted output artifact and the exact consumer input
    # binding. Otherwise a valid-looking substitute could be injected on retry.
    source = sources[0]
    producer = session.get(WorkflowNodeRun, source.producer_node_run_id)
    if (
        source.producer_port_id != "project"
        or producer is None
        or producer.workflow_run_id != run_id
        or producer.node_type != "project_source"
        or producer.status != "succeeded"
        or producer.output_artifact_ids_json != [source.id]
        or node.input_artifact_ids_json != [source.id]
    ):
        raise ValidationError("QC Review Queue source has invalid producer or binding provenance")

    # The saved node is the authoritative execution contract. An interrupted
    # retry must not silently change its source QC run or review threshold,
    # including explicit None versus an omitted value. Ignore only runtime
    # identifiers injected by WorkflowExecutionService.
    saved_parameters = dict(node.parameters_json or {})
    supplied_parameters = {
        key: value
        for key, value in parameters.items()
        if key not in {"__workflow_run_id", "__workflow_node_run_id"}
    }
    if supplied_parameters != saved_parameters:
        raise ValidationError("QC review-queue retry parameters changed from saved node")

    request = ReviewQueueCreateRequest(
        source_quality_control_run_id=parameters.get("source_quality_control_run_id"),
        review_below_confidence=parameters.get("review_below_confidence"),
        created_by=f"workflow:{run_id}:{node_run_id}",
    )
    service = ReviewQueueService(session, settings)
    # A saved node owns at most one immutable QC evidence snapshot. A
    # corrupted or previously raced database may contain two queues with the
    # same workflow owner. Never select an arbitrary first queue: that could
    # replay a different scientific snapshot and conceal reviewer history.
    # Preserve both records for explicit researcher-led reconciliation.
    matching_queues = session.scalars(
        select(ReviewQueue)
        .where(
            ReviewQueue.project_id == project_id,
            ReviewQueue.created_by == request.created_by,
        )
        .limit(2)
    ).all()
    if len(matching_queues) > 1:
        raise ValidationError(
            "QC review-queue retry has ambiguous duplicate workflow-owned queues; "
            "preserve both records for manual reconciliation"
        )
    existing = matching_queues[0] if matching_queues else None
    # A completed node has a persisted output contract. If its queue was
    # deleted, reassigned, or replaced, never silently create a new queue or
    # reuse another queue with the same owner. This protects researcher audit
    # history even if an attacker re-signs a substituted artifact payload.
    saved_outputs = node.output_artifact_ids_json
    if saved_outputs and (
        not isinstance(saved_outputs, list)
        or len(saved_outputs) != 1
        or type(saved_outputs[0]) is not str
        or existing is None
    ):
        raise ValidationError("QC review-queue saved output binding is invalid")
    if existing is not None:
        config = dict(existing.configuration_json or {})
        if (
            existing.status != "complete"
            or config.get("review_below_confidence") != request.review_below_confidence
            or (
                request.source_quality_control_run_id is not None
                and config.get("source_quality_control_run_id")
                != request.source_quality_control_run_id
            )
        ):
            raise ValidationError("QC review-queue retry parameters changed or queue incomplete")
        validate_saved_queue_snapshot(existing, existing.items)
        queue = service.get_queue(existing.id)
    else:
        queue = service.create_queue_for_project(project_id, request)

    payload = {
        "schema_version": "workflow-qc-review-queue-0001",
        "project_id": project_id,
        "queue_id": queue.id,
        "item_count": queue.item_count,
        "source_quality_control_run_id": queue.source_quality_control_run_id,
        "formula_id": queue.formula_id,
        "formula_version": queue.formula_version,
        "input_checksums": queue.input_checksums_json,
        "review_status": "requires_researcher_review",
        "priority_score_unit": "dimensionless",
        "workflow_run_id": run_id,
        "workflow_node_run_id": node_run_id,
    }
    if saved_outputs:
        saved_output = session.get(WorkflowArtifact, saved_outputs[0])
        if (
            saved_output is None
            or saved_output.workflow_run_id != run_id
            or saved_output.producer_node_run_id != node_run_id
            or saved_output.producer_port_id != "queue"
            or saved_output.data_type != "review_queue_reference"
            or not isinstance(saved_output.payload_json, dict)
            or saved_output.payload_sha256 != canonical_json_sha256(saved_output.payload_json)
            or saved_output.payload_json != payload
        ):
            raise ValidationError("QC review-queue saved output no longer matches its queue")

    return [{"port_id": "queue", "data_type": "review_queue_reference", "payload": payload}]
