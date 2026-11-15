"""Validate and rebuild workflow graph/run provenance across exchange."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.services.workflow_provenance import (
    build_workflow_run_provenance,
    verify_succeeded_node_artifacts,
)
from reefvision.storage.datasets import canonical_json_sha256

# These payloads bind nested, historical hashes to source UUIDs. Preserve them
# verbatim and expose the source-to-local map on the imported archive record.
HISTORICAL_ARTIFACT_TYPES = frozenset(
    {
        "ecology_identity_registry",
        "ecology_measurement_candidates",
        "ecology_candidate_report",
        "ecology_measurement_csv",
        "ecology_population_csv",
        "connected_branch_preview",
        "coral_branch_growth",
    }
)


def validate_workflow_rows(sections: dict[str, list[dict[str, Any]]]) -> None:
    graphs = {row["id"]: row for row in sections.get("workflow_graphs", [])}
    runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
    artifacts = {row["id"]: row for row in sections.get("workflow_artifacts", [])}
    skeletons = {row["id"]: row for row in sections.get("skeleton_analysis_revisions", [])}
    scientific_inputs = {
        "ecology_coral_growth": (
            "correspondence_revision_id",
            {row["id"] for row in sections.get("coral_branch_correspondence_revisions", [])},
        ),
        "ecology_verified_analysis": (
            "analysis_id",
            {row["id"] for row in sections.get("ecology_analysis_records", [])},
        ),
    }
    for node in nodes.values():
        config = scientific_inputs.get(node["node_type"])
        if config:
            field, target_ids = config
            target = node["parameters_json"].get(field)
            if target and target not in target_ids:
                raise ValidationError(f"Workflow archive has an unresolved {field} input")
    for graph in graphs.values():
        if canonical_json_sha256(graph["graph_json"]) != graph["graph_sha256"]:
            raise ValidationError("Workflow exchange graph checksum mismatch")
    for run in runs.values():
        graph = graphs[run["workflow_graph_record_id"]]
        result = run["result_json"]
        provenance = result.get("provenance_manifest")
        if graph["graph_sha256"] != run["graph_sha256"] or (
            provenance is not None
            and canonical_json_sha256(provenance) != result.get("provenance_sha256")
        ):
            raise ValidationError("Workflow exchange run provenance checksum mismatch")
    for artifact_row in artifacts.values():
        producer = nodes[artifact_row["producer_node_run_id"]]
        if (
            producer["workflow_run_id"] != artifact_row["workflow_run_id"]
            or artifact_row["workflow_run_id"] not in runs
            or canonical_json_sha256(artifact_row["payload_json"]) != artifact_row["payload_sha256"]
        ):
            raise ValidationError("Workflow exchange artifact lineage or checksum mismatch")
        if artifact_row["data_type"] == "coral_skeleton_candidate":
            proposal = artifact_row["payload_json"]
            analysis = skeletons.get(proposal.get("analysis_id"))
            if (
                analysis is None
                or any(
                    proposal.get(field) != analysis.get(source_field)
                    for field, source_field in (
                        ("image_id", "image_id"),
                        ("mask_annotation_id", "mask_annotation_id"),
                        ("mask_revision", "mask_revision"),
                        ("analysis_sha256", "result_sha256"),
                        ("mask_sha256", "input_mask_sha256"),
                        ("calibration_sha256", "calibration_sha256"),
                        ("parameters_sha256", "parameters_sha256"),
                    )
                )
                or proposal.get("evidence_level") != "proposal_unverified"
            ):
                raise ValidationError(
                    "Workflow branch candidates disagree with their source analysis"
                )
    for node in nodes.values():
        for kind in ("input", "output"):
            for artifact_id in node[f"{kind}_artifact_ids_json"]:
                artifact = artifacts.get(artifact_id)
                if (
                    artifact is None
                    or artifact["workflow_run_id"] != node["workflow_run_id"]
                    or (kind == "output" and artifact["producer_node_run_id"] != node["id"])
                ):
                    raise ValidationError("Workflow exchange node has invalid input/output lineage")
        for output in node["result_json"].get("outputs", []):
            artifact = artifacts.get(output["artifact_id"])
            if (
                artifact is None
                or artifact["producer_node_run_id"] != node["id"]
                or artifact["payload_sha256"] != output["payload_sha256"]
                or artifact["data_type"] != output["data_type"]
                or artifact["producer_port_id"] != output["port_id"]
            ):
                raise ValidationError("Workflow exchange node output checksum mismatch")


def restore_workflow_provenance(
    session: Session,
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
    digest_map: dict[str, str],
    map_values: Callable[[Any, dict[str, str]], Any],
) -> None:
    artifacts = {id_map[row["id"]]: row for row in sections.get("workflow_artifacts", [])}
    for original in sections.get("workflow_graphs", []):
        graph = session.get(WorkflowGraphRecord, id_map[original["id"]])
        if graph is None:
            raise ValidationError("Imported workflow graph is missing")
        graph_payload = deepcopy(graph.graph_json)
        for node in graph_payload["nodes"]:
            if "parameters" in node:
                node["parameters"] = _restore_parameters(
                    node["node_type"], node["parameters"], digest_map
                )
        graph.graph_json = graph_payload
        graph.graph_sha256 = canonical_json_sha256(graph_payload)
        digest_map[original["graph_sha256"]] = graph.graph_sha256

    runs = session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id)).all()
    for run in runs:
        graph = session.get(WorkflowGraphRecord, run.workflow_graph_record_id)
        if graph is None:
            raise ValidationError("Imported workflow run is missing its graph")
        run.graph_sha256 = graph.graph_sha256
        nodes = session.scalars(
            select(WorkflowNodeRun)
            .where(WorkflowNodeRun.workflow_run_id == run.id)
            .order_by(WorkflowNodeRun.execution_order)
        ).all()
        for node in nodes:
            node.parameters_json = _restore_parameters(
                node.node_type, node.parameters_json, digest_map
            )
            for identifier in node.output_artifact_ids_json or []:
                artifact = session.get(WorkflowArtifact, identifier)
                if artifact is None:
                    raise ValidationError("Imported workflow output artifact is missing")
                original = artifacts[artifact.id]
                if artifact.data_type in HISTORICAL_ARTIFACT_TYPES:
                    artifact.payload_json = deepcopy(original["payload_json"])
                else:
                    artifact.payload_json = map_values(artifact.payload_json, digest_map)
                    if artifact.data_type == "reefpose_validation_report":
                        artifact.payload_json = _restore_report_link(
                            session, project_id, artifact.payload_json
                        )
                    elif artifact.data_type == "verified_ecology_analysis":
                        artifact.payload_json["snapshot"] = deepcopy(
                            original["payload_json"]["snapshot"]
                        )
                        artifact.payload_json["source_id_map"] = {
                            origin: id_map.get(imported, imported)
                            for origin, imported in original["payload_json"]
                            .get("source_id_map", {})
                            .items()
                        }
                artifact.payload_sha256 = canonical_json_sha256(artifact.payload_json)
                digest_map[original["payload_sha256"]] = artifact.payload_sha256
            session.flush()
            node.result_json = map_values(node.result_json or {}, digest_map)
            if node.status == "succeeded":
                try:
                    verify_succeeded_node_artifacts(session, run_id=run.id, node_run=node)
                except ConflictError as exc:
                    raise ValidationError(str(exc)) from exc
        result = map_values(run.result_json or {}, digest_map)
        if result.get("provenance_manifest"):
            provenance = build_workflow_run_provenance(session, run_id=run.id)
            replacement = canonical_json_sha256(provenance)
            digest_map[result["provenance_sha256"]] = replacement
            result["provenance_sha256"] = replacement
            result["provenance_manifest"] = provenance
        run.result_json = result
        if run.job_id is not None:
            job = session.get(Job, run.job_id)
            if job is not None:
                job.result_json = map_values(job.result_json or {}, digest_map)


def _restore_parameters(
    node_type: str, parameters: dict[str, Any], digests: dict[str, str]
) -> dict[str, Any]:
    previous = parameters.get("manifest_sha256")
    if (
        node_type == "reefpose_reference_source"
        and isinstance(previous, str)
        and previous in digests
    ):
        return {**parameters, "manifest_sha256": digests[previous]}
    return parameters


def _restore_report_link(
    session: Session, project_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    job_id = payload.get("job_id")
    job = session.get(Job, job_id) if isinstance(job_id, str) else None
    if (
        job is None
        or job.project_id != project_id
        or job.job_type != "reefpose_validation"
        or job.status != "succeeded"
        or not job.result_json
        or payload.get("reference_id") != job.result_json.get("reference_id")
        or payload.get("result_sha256") != job.result_json.get("result_sha256")
    ):
        raise ValidationError("Imported workflow artifact disagrees with its ReefPose report")
    return {
        **payload,
        "input_sha256": job.result_json["input_sha256"],
        "export_path": f"/projects/{project_id}/reefpose-validations/{job_id}/export",
    }
