"""Canonical workflow-run provenance and persisted-artifact integrity."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import (
    ConflictError,
    NotFoundError,
)
from reefvision.storage.datasets import (
    canonical_json_sha256,
)

WORKFLOW_PROVENANCE_SCHEMA_VERSION = "workflow-run-provenance-0001"


def verify_workflow_artifact(
    artifact: WorkflowArtifact,
    *,
    expected_run_id: str | None = None,
) -> str:
    """Fail closed if a persisted workflow artifact no longer matches its SHA."""

    if expected_run_id is not None and artifact.workflow_run_id != expected_run_id:
        raise ConflictError("Workflow artifact belongs to a different workflow run")

    # A JSON array of key/value pairs can coerce to the same dictionary and
    # digest as the original payload. Preserve the stored artifact type.
    if not isinstance(artifact.payload_json, dict):
        raise ConflictError("Workflow artifact payload must be a JSON object")

    actual = canonical_json_sha256(artifact.payload_json)

    if actual != artifact.payload_sha256:
        raise ConflictError(f"Workflow artifact checksum failed for {artifact.id}")

    return actual


def _artifact_ref(
    artifact: WorkflowArtifact,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact.id,
        "producer_node_run_id": (artifact.producer_node_run_id),
        "producer_port_id": (artifact.producer_port_id),
        "data_type": artifact.data_type,
        "payload_sha256": (artifact.payload_sha256),
    }


def _artifact_by_id(
    session: Session,
    artifact_id: str,
    *,
    run_id: str,
) -> WorkflowArtifact:
    artifact = session.get(
        WorkflowArtifact,
        artifact_id,
    )

    if artifact is None:
        raise ConflictError(f"Workflow references a missing artifact: {artifact_id}")

    verify_workflow_artifact(
        artifact,
        expected_run_id=run_id,
    )

    return artifact


def verify_succeeded_node_artifacts(
    session: Session,
    *,
    run_id: str,
    node_run: WorkflowNodeRun,
) -> dict[str, Any]:
    """Verify every persisted input/output before a succeeded node is reused."""

    if node_run.workflow_run_id != run_id:
        raise ConflictError("Workflow node belongs to a different run")

    input_ids = [str(value) for value in node_run.input_artifact_ids_json or []]

    output_ids = [str(value) for value in node_run.output_artifact_ids_json or []]

    inputs = [
        _artifact_by_id(
            session,
            artifact_id,
            run_id=run_id,
        )
        for artifact_id in input_ids
    ]

    outputs = [
        _artifact_by_id(
            session,
            artifact_id,
            run_id=run_id,
        )
        for artifact_id in output_ids
    ]

    for artifact in outputs:
        if artifact.producer_node_run_id != node_run.id:
            raise ConflictError(
                "Succeeded workflow node references an output produced by another node"
            )

    result = dict(node_run.result_json or {})

    declared_outputs = result.get("outputs")

    # Older records may omit the summary, but an explicitly persisted one
    # must retain its list shape. Otherwise malformed lineage is ignored.
    if "outputs" in result and not isinstance(declared_outputs, list):
        raise ConflictError("Succeeded workflow node output summary must be a list")

    if isinstance(
        declared_outputs,
        list,
    ):
        # The worker writes exactly one declaration per persisted artifact.
        # A duplicate or forged extra entry must not disappear in the ID map.
        if len(declared_outputs) != len(outputs):
            raise ConflictError("Succeeded workflow node output summary count mismatch")

        declarations = {
            str(item.get("artifact_id")): item
            for item in declared_outputs
            if isinstance(
                item,
                dict,
            )
            and item.get("artifact_id")
        }

        for artifact in outputs:
            declared = declarations.get(artifact.id)

            if declared is None:
                raise ConflictError(
                    "Succeeded workflow node output summary is missing a persisted artifact"
                )

            if (
                declared.get("port_id") != artifact.producer_port_id
                or declared.get("data_type") != artifact.data_type
                or declared.get("payload_sha256") != artifact.payload_sha256
            ):
                raise ConflictError(
                    "Succeeded workflow node output summary "
                    "does not match persisted artifact provenance"
                )

    return {
        "input_artifact_count": len(inputs),
        "output_artifact_count": len(outputs),
        "input_artifact_ids": [item.id for item in inputs],
        "output_artifact_ids": [item.id for item in outputs],
    }


def build_workflow_run_provenance(
    session: Session,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Build the canonical inspectable lineage manifest for a workflow run."""

    run = session.get(
        WorkflowRun,
        run_id,
    )

    if run is None:
        raise NotFoundError("Workflow run not found")

    graph = session.get(
        WorkflowGraphRecord,
        run.workflow_graph_record_id,
    )

    if graph is None:
        raise NotFoundError("Workflow graph revision not found")

    calculated_graph_sha = canonical_json_sha256(dict(graph.graph_json or {}))

    if calculated_graph_sha != graph.graph_sha256 or graph.graph_sha256 != run.graph_sha256:
        raise ConflictError("Workflow graph provenance checksum failed")

    nodes = list(
        session.scalars(
            select(WorkflowNodeRun)
            .where(WorkflowNodeRun.workflow_run_id == run.id)
            .order_by(
                WorkflowNodeRun.execution_order,
                WorkflowNodeRun.node_id,
            )
        )
    )

    artifacts = list(
        session.scalars(
            select(WorkflowArtifact)
            .where(WorkflowArtifact.workflow_run_id == run.id)
            .order_by(
                WorkflowArtifact.created_at,
                WorkflowArtifact.id,
            )
        )
    )

    artifacts_by_id = {artifact.id: artifact for artifact in artifacts}

    for persisted_artifact in artifacts:
        verify_workflow_artifact(
            persisted_artifact,
            expected_run_id=run.id,
        )

    consumed_ids: set[str] = set()

    node_manifest: list[dict[str, Any]] = []

    for node in nodes:
        input_ids = [str(value) for value in node.input_artifact_ids_json or []]

        output_ids = [str(value) for value in node.output_artifact_ids_json or []]

        consumed_ids.update(input_ids)

        input_refs: list[dict[str, Any]] = []

        output_refs: list[dict[str, Any]] = []

        for artifact_id in input_ids:
            artifact = artifacts_by_id.get(artifact_id)

            if artifact is None:
                raise ConflictError("Workflow provenance references a missing input artifact")

            input_refs.append(_artifact_ref(artifact))

        for artifact_id in output_ids:
            artifact = artifacts_by_id.get(artifact_id)

            if artifact is None:
                raise ConflictError("Workflow provenance references a missing output artifact")

            if artifact.producer_node_run_id != node.id:
                raise ConflictError("Workflow provenance output producer mismatch")

            output_refs.append(_artifact_ref(artifact))

        result = dict(node.result_json or {})

        review_approval = result.get("review_approval")

        node_manifest.append(
            {
                "node_run_id": node.id,
                "node_id": node.node_id,
                "node_type": node.node_type,
                "execution_order": (node.execution_order),
                "status": node.status,
                "parameters": dict(node.parameters_json or {}),
                "parameters_sha256": (canonical_json_sha256(dict(node.parameters_json or {}))),
                "input_artifacts": (input_refs),
                "output_artifacts": (output_refs),
                "review_approval": (
                    dict(review_approval)
                    if isinstance(
                        review_approval,
                        dict,
                    )
                    else None
                ),
                "started_at": (node.started_at.isoformat() if node.started_at else None),
                "completed_at": (node.completed_at.isoformat() if node.completed_at else None),
            }
        )

    terminal = [
        _artifact_ref(artifact) for artifact in artifacts if artifact.id not in consumed_ids
    ]

    result = dict(run.result_json or {})

    raw_history = result.get(
        "recovery_history",
        [],
    )

    recovery_history = (
        list(raw_history)
        if isinstance(
            raw_history,
            list,
        )
        else []
    )

    return {
        "schema_version": (WORKFLOW_PROVENANCE_SCHEMA_VERSION),
        "workflow_run_id": run.id,
        "project_id": run.project_id,
        "parent_job_id": run.job_id,
        "status": run.status,
        "graph": {
            "graph_record_id": (graph.id),
            "graph_key": (graph.graph_key),
            "graph_name": (graph.name),
            "graph_revision": (graph.revision),
            "graph_schema_version": (graph.schema_version),
            "graph_sha256": (graph.graph_sha256),
        },
        "run_inputs": dict(run.input_json or {}),
        "node_count": len(nodes),
        "artifact_count": len(artifacts),
        "nodes": node_manifest,
        "artifacts": [_artifact_ref(artifact) for artifact in artifacts],
        "terminal_artifacts": (terminal),
        "recovery_history": (recovery_history),
        "created_at": (run.created_at.isoformat()),
        "started_at": (run.started_at.isoformat() if run.started_at else None),
        "completed_at": (run.completed_at.isoformat() if run.completed_at else None),
    }
