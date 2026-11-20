"""Validate immutable paired growth receipts and remap only live analysis IDs."""

from typing import Any
from uuid import UUID

from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.ecology_analysis import GrowthResult, validate_ecology_analysis_snapshot
from reefvision.schemas.paired_growth_contrast import (
    PairedGrowthContrastReport,
    PairedGrowthContrastRequest,
    PairedGrowthRosterIdentity,
)
from reefvision.services.paired_growth_contrast import build_paired_growth_report
from reefvision.storage.datasets import canonical_json_sha256

PAIRED_GROWTH_TYPE = "paired_growth_contrast"


def remap_paired_growth_parameters(
    parameters: dict[str, Any], id_map: dict[str, str]
) -> dict[str, Any]:
    identifier = parameters.get("analysis_id")
    if isinstance(identifier, str):
        try:
            canonical = str(UUID(identifier))
        except ValueError:
            return parameters
        if canonical in id_map:
            return {**parameters, "analysis_id": id_map[canonical]}
    return parameters


def _declaration(parameters: dict[str, Any]) -> tuple[str, PairedGrowthContrastRequest]:
    return str(UUID(parameters["analysis_id"])), PairedGrowthContrastRequest.model_validate(
        {key: value for key, value in parameters.items() if key != "analysis_id"}
    )


def validate_paired_growth_exchange(
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
    origin: Any,
) -> None:
    node_rows = sections.get("workflow_node_runs", [])
    receipts = [
        row
        for row in sections.get("workflow_artifacts", [])
        if row.get("data_type") == PAIRED_GROWTH_TYPE
    ]
    paired_producers = [
        row
        for row in node_rows
        if row.get("status") == "succeeded" and row.get("node_type") == PAIRED_GROWTH_TYPE
    ]
    if not receipts and not paired_producers:
        return
    try:
        receipt_producers = [row["producer_node_run_id"] for row in receipts]
        if sorted(receipt_producers) != sorted(row["id"] for row in paired_producers):
            raise ValueError("each completed paired node requires exactly one contrast receipt")
        graphs = {row["id"]: row for row in sections.get("workflow_graphs", [])}
        runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
        nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
        analyses = {row["id"]: row for row in sections.get("ecology_analysis_records", [])}
        identity_rows = {
            (row["organism_key"], row["revision"]): row
            for row in sections.get("ecology_identity_revisions", [])
        }
        origin_ids = origin.get("id_map") if isinstance(origin, dict) else None
        origin_ids = origin_ids if isinstance(origin_ids, dict) else {}

        for receipt in receipts:
            payload = receipt["payload_json"]
            if canonical_json_sha256(payload) != receipt["payload_sha256"]:
                raise ValueError("artifact checksum mismatch")
            report = PairedGrowthContrastReport.model_validate(payload)
            producer = nodes[receipt["producer_node_run_id"]]
            run = runs[receipt["workflow_run_id"]]
            graph = graphs[run["workflow_graph_record_id"]]
            [declared] = [
                entry
                for entry in graph["graph_json"]["nodes"]
                if entry["node_id"] == producer["node_id"]
            ]
            local_analysis_id, request = _declaration(declared["parameters"])
            analysis = analyses[local_analysis_id]
            if (
                receipt["producer_port_id"] != "contrast"
                or producer["status"] != "succeeded"
                or producer["node_type"] != PAIRED_GROWTH_TYPE
                or declared["node_type"] != PAIRED_GROWTH_TYPE
                or producer["workflow_run_id"] != run["id"]
                or _declaration(producer["parameters_json"]) != (local_analysis_id, request)
                or analysis["project_id"] != project_id
                or analysis["content_sha256"] != request.source_sha256
            ):
                raise ValueError("receipt producer, source or request mismatch")
            original_project, original_analysis = str(report.project_id), str(report.analysis_id)
            if original_project == project_id:
                valid_origin = original_analysis == local_analysis_id
            else:
                valid_origin = (
                    origin_ids.get(original_project) == project_id
                    and origin_ids.get(original_analysis) == local_analysis_id
                )
            if not valid_origin:
                raise ValueError("original report and local analysis lineage do not match")

            snapshot = validate_ecology_analysis_snapshot(
                analysis["snapshot_json"], analysis["content_sha256"]
            )
            if not isinstance(snapshot.result, GrowthResult):
                raise ValueError("receipt does not bind a growth analysis")
            identities = {
                key: PairedGrowthRosterIdentity.model_validate(identity_rows[key, revision])
                for key, revision in snapshot.result.sampling_identity_revisions.items()
            }
            expected = build_paired_growth_report(
                report.project_id,
                report.analysis_id,
                snapshot,
                request,
                identities,
                calculate_t_interval=report.interval_status != "statistics_runtime_unavailable",
            )
            if receipt["payload_sha256"] != canonical_json_sha256(expected.model_dump(mode="json")):
                raise ValueError("frozen report does not replay")
    except ValidationError as exc:
        raise ValidationError(
            f"Paired growth workflow receipt could not be verified. {exc}"
        ) from exc
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ConflictError,
    ) as exc:
        raise ValidationError(
            "Paired growth workflow receipt does not match its producer and frozen analysis"
        ) from exc
