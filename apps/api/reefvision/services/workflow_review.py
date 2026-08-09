"""Human-review pause and resume semantics for persistent workflow runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ClassificationPrediction,
    Job,
    PredictionProposal,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.workflow_execution import (
    WorkflowReviewResumeRequest,
    WorkflowRunResponse,
)
from reefvision.services.workflow_auto_label import (
    ensure_disagreement_active_learning_round,
    materialize_consensus_annotations,
)

REVIEW_GATE_NODE_TYPES = {
    "detection_review_gate",
    "mask_review_gate",
    "classification_review_gate",
}


class WorkflowReviewRequired(RuntimeError):
    """Signal that execution reached a human-review boundary instead of failing."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def _now() -> datetime:
    return datetime.now(UTC)


def _input_artifacts(session: Session, node_run: WorkflowNodeRun) -> list[WorkflowArtifact]:
    artifact_ids = [str(value) for value in node_run.input_artifact_ids_json or []]
    if not artifact_ids:
        return []
    artifacts = list(
        session.scalars(
            select(WorkflowArtifact).where(WorkflowArtifact.id.in_(artifact_ids))
        )
    )
    by_id = {artifact.id: artifact for artifact in artifacts}
    return [by_id[artifact_id] for artifact_id in artifact_ids if artifact_id in by_id]


def _pending_review_count(session: Session, artifacts: list[WorkflowArtifact]) -> int:
    proposal_ids: set[str] = set()
    classification_ids: set[str] = set()
    for artifact in artifacts:
        payload = dict(artifact.payload_json or {})
        if artifact.data_type in {"detection_proposals", "mask_proposals"}:
            proposal_ids.update(str(value) for value in payload.get("proposal_ids", []))
        elif artifact.data_type == "classification_predictions":
            classification_ids.update(
                str(value) for value in payload.get("prediction_ids", [])
            )

    pending = 0
    if proposal_ids:
        pending += int(
            session.scalar(
                select(func.count(PredictionProposal.id)).where(
                    PredictionProposal.id.in_(proposal_ids),
                    PredictionProposal.review_status == "pending",
                )
            )
            or 0
        )
    if classification_ids:
        pending += int(
            session.scalar(
                select(func.count(ClassificationPrediction.id)).where(
                    ClassificationPrediction.id.in_(classification_ids),
                    ClassificationPrediction.status == "pending",
                )
            )
            or 0
        )
    return pending


def _disagreement_artifact_for_consensus(
    session: Session,
    consensus_artifact: WorkflowArtifact,
) -> WorkflowArtifact | None:
    return session.scalar(
        select(WorkflowArtifact)
        .where(
            WorkflowArtifact.workflow_run_id == consensus_artifact.workflow_run_id,
            WorkflowArtifact.producer_node_run_id == consensus_artifact.producer_node_run_id,
            WorkflowArtifact.data_type == "detection_disagreements",
        )
        .order_by(WorkflowArtifact.created_at.desc(), WorkflowArtifact.id.desc())
        .limit(1)
    )


def _auto_label_post_review(
    session: Session,
    *,
    project_id: str,
    artifacts: list[WorkflowArtifact],
    reviewed_by: str,
) -> dict[str, Any]:
    consensus_artifacts = [
        artifact for artifact in artifacts if artifact.data_type == "detection_consensus"
    ]
    if not consensus_artifacts:
        return {}

    materialized: list[dict[str, Any]] = []
    active_learning: list[dict[str, Any]] = []
    for consensus_artifact in consensus_artifacts:
        materialized.append(
            materialize_consensus_annotations(
                session,
                project_id=project_id,
                artifact=consensus_artifact,
                reviewed_by=reviewed_by,
            )
        )
        disagreement_artifact = _disagreement_artifact_for_consensus(
            session,
            consensus_artifact,
        )
        if disagreement_artifact is None:
            continue
        handoff = ensure_disagreement_active_learning_round(
            session,
            project_id=project_id,
            artifact=disagreement_artifact,
            created_by=reviewed_by,
        )
        if handoff is not None:
            active_learning.append(
                {
                    "source_artifact_id": disagreement_artifact.id,
                    **handoff,
                }
            )

    return {
        "consensus_materialization": materialized,
        "active_learning_handoff": active_learning,
    }


def resume_review_gate(
    session: Session,
    node_run_id: str,
    request: WorkflowReviewResumeRequest,
) -> WorkflowRunResponse:
    node_run = session.get(WorkflowNodeRun, node_run_id)
    if node_run is None:
        raise NotFoundError("Workflow review node was not found")
    if node_run.node_type not in REVIEW_GATE_NODE_TYPES:
        raise ValidationError("Only human-review workflow nodes can be resumed")
    if node_run.status != "waiting_for_review":
        raise ConflictError("Workflow node is not waiting for review")

    run = session.get(WorkflowRun, node_run.workflow_run_id)
    if run is None or run.job_id is None:
        raise NotFoundError("Workflow run or parent job was not found")
    job = session.get(Job, run.job_id)
    if job is None:
        raise NotFoundError("Workflow parent job was not found")
    if run.status != "waiting_for_review" or job.status != "waiting_for_review":
        raise ConflictError("Workflow run is not paused at this review node")

    artifacts = _input_artifacts(session, node_run)
    pending_count = _pending_review_count(session, artifacts)
    if pending_count:
        raise ValidationError(
            f"{pending_count} model prediction(s) are still pending review"
        )

    auto_label_result = (
        _auto_label_post_review(
            session,
            project_id=run.project_id,
            artifacts=artifacts,
            reviewed_by=request.reviewed_by,
        )
        if node_run.node_type == "detection_review_gate"
        else {}
    )

    now = _now()
    result = dict(node_run.result_json or {})
    result["review_approval"] = {
        "reviewed_by": request.reviewed_by,
        "note": request.note,
        "approved_at": now.isoformat(),
        "input_artifact_ids": [artifact.id for artifact in artifacts],
        **auto_label_result,
    }
    node_run.result_json = result
    node_run.status = "review_approved"
    node_run.error_message = None
    node_run.completed_at = None

    succeeded_count = int(
        session.scalar(
            select(func.count(WorkflowNodeRun.id)).where(
                WorkflowNodeRun.workflow_run_id == run.id,
                WorkflowNodeRun.status == "succeeded",
            )
        )
        or 0
    )
    run.status = "queued"
    run.error_message = None
    run.completed_at = None
    run.result_json = {
        **dict(run.result_json or {}),
        "stage": "queued",
        "completed_nodes": succeeded_count,
        "resumed_from_review_node_id": node_run.id,
    }
    job.status = "queued"
    job.progress_current = succeeded_count
    job.error_message = None
    job.completed_at = None
    job.result_json = {
        **dict(job.result_json or {}),
        "stage": "queued",
        "completed_nodes": succeeded_count,
        "resumed_from_review_node_id": node_run.id,
    }
    session.commit()
    session.refresh(run)
    return WorkflowRunResponse.model_validate(run)
