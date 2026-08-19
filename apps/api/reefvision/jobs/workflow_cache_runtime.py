"""Allow deterministic upstream cache reuse when a later workflow node fails.

Human review intentionally creates a two-pass workflow: segmentation succeeds, measurement
fails closed while proposals are pending, then the workflow is rerun after review. Cache
reuse therefore preserves the exact cached artifact payload and checksum. Cache-hit
provenance already lives in WorkflowRun.node_state_json; mutating the copied artifact payload
would change downstream cache keys and incorrectly regenerate reviewed segmentation masks.

Cache lookup also chooses one newest eligible source run. Mixing outputs from multiple
historical runs can duplicate the same node/port in the destination run and violate the
workflow artifact uniqueness contract.
"""

from __future__ import annotations

from collections.abc import Iterable

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


def _select_cached_source_artifacts(
    rows: Iterable[tuple[WorkflowArtifact, WorkflowRun]],
    *,
    current_run_id: str,
    node_id: str,
    cache_key: str,
) -> list[WorkflowArtifact]:
    """Select the complete output set from one newest eligible source run."""

    matches = [
        (artifact, source_run)
        for artifact, source_run in rows
        if source_run.id != current_run_id
        and _node_cache_eligible(source_run, node_id)
        and workflow_runs._artifact_payload(artifact).get("_cache_key") == cache_key
    ]
    if not matches:
        return []
    source_run_id = matches[0][1].id
    return sorted(
        [artifact for artifact, source_run in matches if source_run.id == source_run_id],
        key=lambda artifact: artifact.port_name,
    )


def _review_resumable_cached_outputs(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    cache_key: str,
) -> list[WorkflowArtifact]:
    result = session.execute(
        select(WorkflowArtifact, WorkflowRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowArtifact.workflow_run_id)
        .where(
            WorkflowRun.project_id == run.project_id,
            WorkflowArtifact.node_id == node_id,
            WorkflowRun.status.in_(("succeeded", "failed")),
        )
        .order_by(WorkflowArtifact.created_at.desc(), WorkflowArtifact.id.desc())
    )
    rows: list[tuple[WorkflowArtifact, WorkflowRun]] = [
        (artifact, source_run) for artifact, source_run in result
    ]
    return _select_cached_source_artifacts(
        rows,
        current_run_id=run.id,
        node_id=node_id,
        cache_key=cache_key,
    )


def _stable_copy_cached_outputs(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    cached: list[WorkflowArtifact],
) -> list[WorkflowArtifact]:
    """Copy cached artifacts without altering semantic payload/checksum identity."""

    return [
        workflow_runs._save_artifact(
            session,
            run=run,
            node_id=node_id,
            port_name=artifact.port_name,
            artifact_type=artifact.artifact_type,
            payload=workflow_runs._artifact_payload(artifact),
            managed_path=artifact.managed_path,
            size_bytes=artifact.size_bytes,
        )
        for artifact in cached
    ]


def install_workflow_cache_runtime() -> None:
    if workflow_runs._cached_outputs is not _review_resumable_cached_outputs:
        workflow_runs._cached_outputs = _review_resumable_cached_outputs
    if workflow_runs._copy_cached_outputs is not _stable_copy_cached_outputs:
        workflow_runs._copy_cached_outputs = _stable_copy_cached_outputs


install_workflow_cache_runtime()
