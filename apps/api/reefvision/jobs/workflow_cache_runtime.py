"""Allow deterministic upstream cache reuse when a later workflow node fails.

Human review intentionally creates a two-pass workflow: segmentation succeeds, measurement
fails closed while proposals are pending, then the workflow is rerun after review. The base
cache previously required the entire source run to have succeeded, which regenerated the
reviewed proposals. This patch reuses artifacts only when that exact source node is recorded
as succeeded, preserving deterministic cache safety while supporting review/resume flows.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs


def _node_cache_eligible(source_run: WorkflowRun, node_id: str) -> bool:
    if source_run.status == "succeeded":
        return True
    if source_run.status != "failed":
        return False
    raw_state = dict(source_run.node_state_json or {}).get(node_id)
    return isinstance(raw_state, dict) and raw_state.get("status") == "succeeded"


def _review_resumable_cached_outputs(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    cache_key: str,
) -> list[WorkflowArtifact]:
    rows = list(
        session.execute(
            select(WorkflowArtifact, WorkflowRun)
            .join(WorkflowRun, WorkflowRun.id == WorkflowArtifact.workflow_run_id)
            .where(
                WorkflowRun.project_id == run.project_id,
                WorkflowArtifact.node_id == node_id,
                WorkflowRun.status.in_(("succeeded", "failed")),
            )
            .order_by(WorkflowArtifact.created_at.desc())
        )
    )
    return [
        artifact
        for artifact, source_run in rows
        if source_run.id != run.id
        and _node_cache_eligible(source_run, node_id)
        and workflow_runs._artifact_payload(artifact).get("_cache_key") == cache_key
    ]


workflow_runs._cached_outputs = _review_resumable_cached_outputs
