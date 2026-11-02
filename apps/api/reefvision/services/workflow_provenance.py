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


def _artifact_ids(value: Any, *, field: str) -> list[str]:
    """Reject malformed persisted lineage instead of iterating JSON object keys."""

    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ConflictError(f"Workflow node {field} must be a list of artifact IDs")
    # One produced artifact has one output identity. Repeated inputs can be
    # legitimate fan-out across different ports, but repeated outputs cannot.
    if field == "output IDs" and len(value) != len(set(value)):
        raise ConflictError("Workflow node output IDs contain duplicates")
    return value


def verify_succeeded_node_artifacts(
    session: Session,
    *,
    run_id: str,
    node_run: WorkflowNodeRun,
) -> dict[str, Any]:
    """Verify every persisted input/output before a succeeded node is reused."""

    if node_run.workflow_run_id != run_id:
        raise ConflictError("Workflow node belongs to a different run")

    input_ids = _artifact_ids(node_run.input_artifact_ids_json, field="input IDs")

    output_ids = _artifact_ids(node_run.output_artifact_ids_json, field="output IDs")

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

    # The planner saves input artifact IDs in edge-ID order. Comparing only
    # counts allows two valid inputs to be swapped between different target
    # ports without changing any artifact checksum or producer identity.
    actual_bindings: list[tuple[str, str]] = []
    for artifact in inputs:
        producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
        if (
            producer is None
            or producer.workflow_run_id != run_id
            or producer.status != "succeeded"
            or producer.execution_order >= node_run.execution_order
        ):
            raise ConflictError("Succeeded workflow node input lacks an earlier succeeded producer")
        actual_bindings.append((producer.node_id, artifact.producer_port_id))

    run = session.get(WorkflowRun, run_id)
    graph = session.get(WorkflowGraphRecord, run.workflow_graph_record_id) if run else None
    if graph is None or not isinstance(graph.graph_json, dict):
        raise ConflictError("Succeeded workflow node graph lineage is unavailable")
    raw_edges = graph.graph_json.get("edges", [])
    if not isinstance(raw_edges, list) or any(
        not isinstance(edge, dict) or not isinstance(edge.get("edge_id"), str) for edge in raw_edges
    ):
        raise ConflictError("Succeeded workflow node graph edges are invalid")
    expected_bindings = [
        (edge.get("source_node_id"), edge.get("source_port_id"))
        for edge in sorted(raw_edges, key=lambda edge: edge["edge_id"])
        if edge.get("target_node_id") == node_run.node_id
    ]
    if actual_bindings != expected_bindings:
        raise ConflictError("Succeeded workflow node inputs do not match saved graph edges")

    for artifact in outputs:
        if artifact.producer_node_run_id != node_run.id:
            raise ConflictError(
                "Succeeded workflow node references an output produced by another node"
            )

    # A JSON array of key/value pairs can coerce into the original dictionary,
    # concealing structural corruption of persisted scientific run evidence.
    if node_run.result_json is not None and not isinstance(node_run.result_json, dict):
        raise ConflictError("Succeeded workflow node result must be a JSON object")

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


def verify_completed_run_artifact_ownership(
    run: WorkflowRun,
    nodes: list[WorkflowNodeRun],
    artifacts: list[WorkflowArtifact],
) -> None:
    """Reject undeclared artifacts in a completed scientific workflow run."""

    # Interrupted or review-paused runs can still be recovering their node
    # declarations. A succeeded run must account for every saved artifact.
    if run.status != "succeeded":
        return

    # Terminal success means every planned operation completed. A failed or
    # pending node with no artifacts could otherwise masquerade as a fully
    # reproducible scientific run because ownership checks only see outputs.
    if any(node.status != "succeeded" for node in nodes):
        raise ConflictError("Succeeded workflow run contains an incomplete node")

    declared_by_producer = {
        node.id: set(_artifact_ids(node.output_artifact_ids_json, field="output IDs"))
        for node in nodes
        if node.status == "succeeded"
    }
    for artifact in artifacts:
        producer_outputs = declared_by_producer.get(artifact.producer_node_run_id, set())
        if artifact.id not in producer_outputs:
            raise ConflictError("Succeeded workflow run contains an undeclared output artifact")


def verify_workflow_run_node_graph_lineage(
    graph: WorkflowGraphRecord,
    nodes: list[WorkflowNodeRun],
) -> None:
    """Bind saved node identities to the checksum-pinned workflow graph."""

    raw_nodes = graph.graph_json.get("nodes")
    error = "Workflow run node lineage does not match saved graph"
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ConflictError(error)

    expected: dict[str, tuple[str, dict[str, Any]]] = {}
    for item in raw_nodes:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("node_id"), str)
            or not isinstance(item.get("node_type"), str)
            or not isinstance(item.get("parameters", {}), dict)
            or item["node_id"] in expected
        ):
            raise ConflictError(error)
        expected[item["node_id"]] = (item["node_type"], item.get("parameters", {}))

    if len(nodes) != len(expected):
        raise ConflictError(error)

    # The planner persists a one-based, contiguous execution order. Missing,
    # duplicated, or out-of-range positions corrupt the scientific run order
    # even when node IDs and types still match the checksum-pinned graph.
    expected_orders = list(range(1, len(expected) + 1))
    if sorted(node.execution_order for node in nodes) != expected_orders:
        raise ConflictError(error)

    seen: set[str] = set()
    for node in nodes:
        graph_node = expected.get(node.node_id)
        if node.node_id in seen or graph_node is None or graph_node[0] != node.node_type:
            raise ConflictError(error)
        # A missing parameter object must not erase explicitly pinned
        # scientific inputs (for example, a frozen pose dataset checksum).
        if node.parameters_json is None and graph_node[1]:
            raise ConflictError(error)
        # Pending and review-paused nodes also carry scientific audit data.
        # A JSON array of pairs must not be coerced into a result object.
        if node.result_json is not None and not isinstance(node.result_json, dict):
            raise ConflictError("Workflow node result must be a JSON object")
        # The planner may add optional defaults, but it must preserve every
        # explicitly saved scientific parameter from the checksum-pinned graph.
        if isinstance(node.parameters_json, dict) and any(
            key not in node.parameters_json or node.parameters_json[key] != value
            for key, value in graph_node[1].items()
        ):
            raise ConflictError(error)
        seen.add(node.node_id)

    # A contiguous sequence is insufficient: swapping a producer with its
    # consumer preserves every position while falsifying execution lineage.
    positions = {node.node_id: node.execution_order for node in nodes}
    edges = graph.graph_json.get("edges", [])
    if not isinstance(edges, list):
        raise ConflictError(error)
    incoming_counts = {node_id: 0 for node_id in positions}
    for edge in edges:
        if not isinstance(edge, dict):
            raise ConflictError(error)
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        if (
            not isinstance(source_id, str)
            or not isinstance(target_id, str)
            or source_id not in positions
            or target_id not in positions
            or positions[source_id] >= positions[target_id]
        ):
            raise ConflictError(error)
        incoming_counts[target_id] += 1

    # A completed node must retain one recorded input for each pinned graph
    # edge. Otherwise deleting an input ID can erase scientific dependencies
    # without altering the graph checksum or any remaining artifact digest.
    for node in nodes:
        if (
            node.status == "succeeded"
            and len(_artifact_ids(node.input_artifact_ids_json, field="input IDs"))
            != incoming_counts[node.node_id]
        ):
            raise ConflictError("Succeeded workflow node input count does not match saved graph")


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

    # A digest authenticates graph contents, not the owning project or the
    # saved revision identity. Match the run-detail API's lineage checks.
    if (
        graph.project_id != run.project_id
        or not isinstance(graph.graph_json, dict)
        or graph.graph_key != graph.graph_json.get("graph_id")
        or graph.schema_version != graph.graph_json.get("schema_version")
        or graph.graph_sha256 != run.graph_sha256
        or canonical_json_sha256(graph.graph_json) != run.graph_sha256
    ):
        raise ConflictError("Workflow graph provenance checksum failed")

    # Persisted run inputs and results are scientific evidence. Coercing a
    # JSON array of pairs to a dict can hide changes to its original shape.
    if run.input_json is not None and not isinstance(run.input_json, dict):
        raise ConflictError("Workflow run inputs must be a JSON object")
    if run.result_json is not None and not isinstance(run.result_json, dict):
        raise ConflictError("Workflow run result must be a JSON object")

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

    verify_workflow_run_node_graph_lineage(graph, nodes)

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

    verify_completed_run_artifact_ownership(run, nodes, artifacts)

    for persisted_artifact in artifacts:
        verify_workflow_artifact(
            persisted_artifact,
            expected_run_id=run.id,
        )

    consumed_ids: set[str] = set()

    node_manifest: list[dict[str, Any]] = []

    for node in nodes:
        # Provenance export must enforce the same succeeded-node output
        # declarations as run-detail retrieval and interrupted-run replay.
        if node.status == "succeeded":
            verify_succeeded_node_artifacts(session, run_id=run.id, node_run=node)

        input_ids = _artifact_ids(node.input_artifact_ids_json, field="input IDs")

        output_ids = _artifact_ids(node.output_artifact_ids_json, field="output IDs")

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

        # Preserve the persisted parameter JSON type in exported scientific
        # provenance; dict(list_of_pairs) would conceal a corrupted record.
        if node.parameters_json is not None and not isinstance(node.parameters_json, dict):
            raise ConflictError("Workflow node parameters must be a JSON object")

        result = dict(node.result_json or {})

        review_approval = result.get("review_approval")

        # An explicitly persisted approval is scientific review evidence.
        # Do not silently turn a malformed approval into an absent one.
        if review_approval is not None and not isinstance(review_approval, dict):
            raise ConflictError("Workflow node review approval must be a JSON object")

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

    # An explicitly saved recovery history is scientific audit evidence.
    # Never silently discard malformed entries from a persisted run.
    if "recovery_history" in result and not isinstance(raw_history, list):
        raise ConflictError("Workflow recovery history must be a list")
    # The list itself can be valid while individual audit entries have been
    # replaced with scalars. Preserve recovery-event structure on export.
    if any(not isinstance(entry, dict) for entry in raw_history):
        raise ConflictError("Workflow recovery history entries must be JSON objects")

    recovery_history = list(raw_history)

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
