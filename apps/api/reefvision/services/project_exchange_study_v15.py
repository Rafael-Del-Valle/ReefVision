"""Preserve immutable study receipts and validate their typed Exchange references."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.ecology_analysis import validate_ecology_analysis_snapshot
from reefvision.schemas.ecology_study_assignment import EcologyStudyAssignmentRead
from reefvision.schemas.study_design import (
    StudyDesignReplay,
    StudyDesignRosterMember,
    StudyDesignSnapshot,
    validate_study_design_snapshot,
)
from reefvision.services.study_design import rebuild_study_binding, validate_study_roster
from reefvision.storage.datasets import canonical_json_sha256

SECTION = "study_design_revisions"
NODE_TYPE = "reviewed_study_design"
ARTIFACT_TYPE = "study_design_report"


@dataclass(frozen=True)
class ArchivedStudy:
    row: dict[str, Any]
    snapshot: StudyDesignSnapshot
    live_roster: tuple[str, ...]


def _references(snapshot: StudyDesignSnapshot) -> set[str]:
    return {
        str(reference)
        for reference in (
            snapshot.project_id,
            snapshot.design_id,
            snapshot.revision_id,
            snapshot.supersedes_revision_id,
            snapshot.binding.analysis_id if snapshot.binding else None,
            *(member.identity_id for member in snapshot.roster),
        )
        if reference is not None
    }


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _mapped(original: UUID | None, local: Mapping[str, str]) -> str | None:
    return local.get(str(original), str(original)) if original is not None else None


def _read_record(
    row: dict[str, Any],
    project_id: str,
    identity_rows: dict[str, dict[str, Any]],
    identity_history: dict[str, list[dict[str, Any]]],
    analysis_rows: dict[str, dict[str, Any]],
    origin_map: Mapping[str, str],
) -> ArchivedStudy:
    snapshot = validate_study_design_snapshot(row["snapshot_json"], row["content_sha256"])
    bound = snapshot.binding
    local = row["source_id_map_json"]
    original_references = _references(snapshot)
    if (
        row["project_id"] != project_id
        or set(local) - original_references
        or any(local.get(key, key) != origin_map.get(key, key) for key in original_references)
        or _mapped(snapshot.project_id, local) != project_id
        or _mapped(snapshot.revision_id, local) != row["id"]
        or _mapped(snapshot.design_id, local) != row["design_id"]
        or _mapped(snapshot.supersedes_revision_id, local) != row["supersedes_revision_id"]
        or snapshot.revision != row["revision"]
        or snapshot.created_at != _time(row["created_at"])
        or _mapped(bound.analysis_id if bound else None, local) != row["growth_analysis_id"]
        or (bound.source_sha256 if bound else None) != row["growth_source_sha256"]
    ):
        raise ValueError(
            "Original study IDs, history or growth source do not match the live archive"
        )
    validate_study_roster(snapshot.declaration, snapshot.roster)
    live_roster = []
    for member in snapshot.roster:
        live_id = _mapped(member.identity_id, local)
        identity = identity_rows[str(live_id)]
        actual = StudyDesignRosterMember(
            identity_id=member.identity_id,
            organism_key=identity["organism_key"],
            identity_revision=identity["revision"],
            kind=identity["kind"],
            parent_colony_key=identity["parent_colony_key"],
            experimental_unit_type=identity["experimental_unit_type"],
            experimental_unit_id=identity["experimental_unit_id"],
            assignment=EcologyStudyAssignmentRead.model_validate(identity["study_assignment"]),
        )
        if (
            identity["project_id"] != project_id
            or actual != member
            or _time(identity["created_at"]) > snapshot.declared_at
            or member.assignment.reviewed_at > snapshot.declared_at
            or any(
                entry["revision"] > member.identity_revision
                and _time(entry["created_at"]) <= snapshot.created_at
                for entry in identity_history[member.organism_key]
            )
        ):
            raise ValueError(
                f"Historical reviewed identity does not match the enrolled {member.organism_key}"
            )
        live_roster.append(str(live_id))
    if bound is not None:
        analysis = analysis_rows[row["growth_analysis_id"]]
        analysis_created = _time(analysis["created_at"])
        if (
            analysis["project_id"] != project_id
            or analysis["content_sha256"] != bound.source_sha256
            or analysis_created > snapshot.created_at
        ):
            raise ValueError("Bound growth evidence has a foreign source, digest or chronology")
        source = validate_ecology_analysis_snapshot(analysis["snapshot_json"], bound.source_sha256)
        expected = rebuild_study_binding(
            project_id=snapshot.project_id,
            analysis_id=bound.analysis_id,
            source_sha256=bound.source_sha256,
            analysis_snapshot=source,
            analysis_created_at=analysis_created,
            declaration=snapshot.declaration,
            roster=snapshot.roster,
            declared_at=snapshot.declared_at,
            calculate_t_interval=bound.paired_report.interval_status
            != "statistics_runtime_unavailable",
        )
        if bound != expected:
            raise ValueError(
                "Frozen paired outcome does not replay from the reviewed growth source"
            )

    return ArchivedStudy(row, snapshot, tuple(live_roster))


def _validate_series(studies: dict[str, ArchivedStudy]) -> None:
    children: set[str] = set()
    revisions: set[tuple[str, int]] = set()
    for archived in studies.values():
        row, snapshot = archived.row, archived.snapshot
        key = row["design_id"], snapshot.revision
        if key in revisions:
            raise ValueError("A study series repeats the same revision")
        revisions.add(key)
        parent_id = row["supersedes_revision_id"]
        if parent_id:
            parent = studies[parent_id]
            if (
                parent_id in children
                or parent.row["design_id"] != row["design_id"]
                or parent.snapshot.revision + 1 != snapshot.revision
                or parent.snapshot.created_at > snapshot.created_at
            ):
                raise ValueError("Study design revision ancestry is inconsistent")
            children.add(parent_id)

        if snapshot.declaration.timing == "prospective" and snapshot.binding is not None:
            previous = studies[parent_id]
            if (
                previous.snapshot.binding is not None
                or previous.snapshot.declaration != snapshot.declaration
                or previous.snapshot.declared_at != snapshot.declared_at
                or previous.live_roster != archived.live_roster
            ):
                raise ValueError(
                    "A prospective binding must retain its frozen declaration and roster"
                )
        elif snapshot.declared_at != snapshot.created_at:
            raise ValueError("Study declaration must carry its original freeze timestamp")


def _resolve_workflow_params(
    value: Any, studies: dict[str, ArchivedStudy]
) -> tuple[StudyDesignReplay, ArchivedStudy]:
    params = StudyDesignReplay.model_validate(value)
    study = studies[str(params.design_revision_id)]
    if params.design_sha256 != study.row["content_sha256"]:
        raise ValueError("Saved study node has the wrong frozen revision digest")
    return params, study


def _validate_artifacts(
    sections: dict[str, list[dict[str, Any]]], studies: dict[str, ArchivedStudy]
) -> None:
    declared = {}
    for graph in sections.get("workflow_graphs", []):
        for node in graph["graph_json"]["nodes"]:
            if node["node_type"] == NODE_TYPE:
                declared[graph["id"], node["node_id"]] = _resolve_workflow_params(
                    node["parameters"], studies
                )
    runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    producers = {
        row["id"]: row
        for row in sections.get("workflow_node_runs", [])
        if row["node_type"] == NODE_TYPE and row["status"] == "succeeded"
    }
    artifacts = [
        row for row in sections.get("workflow_artifacts", []) if row["data_type"] == ARTIFACT_TYPE
    ]
    if Counter(row["producer_node_run_id"] for row in artifacts) != Counter(producers.keys()):
        raise ValueError("Every completed study node must have exactly one immutable report")
    for artifact in artifacts:
        producer = producers[artifact["producer_node_run_id"]]
        run = runs[artifact["workflow_run_id"]]
        params, study = declared[run["workflow_graph_record_id"], producer["node_id"]]
        if (
            producer["workflow_run_id"] != run["id"]
            or artifact["producer_port_id"] != "report"
            or StudyDesignReplay.model_validate(producer["parameters_json"]) != params
            or artifact["payload_json"]
            != {
                "content_sha256": study.row["content_sha256"],
                "snapshot": study.row["snapshot_json"],
            }
            or canonical_json_sha256(artifact["payload_json"]) != artifact["payload_sha256"]
        ):
            raise ValueError(
                "Study workflow artifact differs from its immutable design or producer"
            )


def validate_study_exchange(
    project_id: str, sections: dict[str, list[dict[str, Any]]], origin_map: Mapping[str, str]
) -> None:
    """Validate historical records without treating later registry edits as evidence loss."""
    records = sections.get(SECTION, [])
    study_graphs = any(
        isinstance(row.get("graph_json"), dict)
        and isinstance(row["graph_json"].get("nodes"), list)
        and any(
            isinstance(node, dict) and node.get("node_type") == NODE_TYPE
            for node in row["graph_json"]["nodes"]
        )
        for row in sections.get("workflow_graphs", [])
    )
    if (
        not records
        and not study_graphs
        and not any(
            row.get("node_type") == NODE_TYPE for row in sections.get("workflow_node_runs", [])
        )
        and not any(
            row.get("data_type") == ARTIFACT_TYPE for row in sections.get("workflow_artifacts", [])
        )
    ):
        return
    try:
        identities = {row["id"]: row for row in sections.get("ecology_identity_revisions", [])}
        identity_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in identities.values():
            identity_history[row["organism_key"]].append(row)
        analyses = {row["id"]: row for row in sections.get("ecology_analysis_records", [])}
        studies = {
            row["id"]: _read_record(
                row, project_id, identities, identity_history, analyses, origin_map
            )
            for row in records
        }
        if len(studies) != len(records):
            raise ValueError("Duplicated archived study revision")
        _validate_series(studies)
        _validate_artifacts(sections, studies)
    except (ValidationError, ConflictError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValidationError(f"Study design exchange failed integrity validation. {exc}") from exc


def restore_study_row(
    name: str, row: dict[str, Any], values: dict[str, Any], mapping: dict[str, str]
) -> None:
    if name != SECTION:
        return
    snapshot = validate_study_design_snapshot(row["snapshot_json"], row["content_sha256"])
    previous = row["source_id_map_json"]
    values["source_id_map_json"] = {
        original: mapping[previous.get(original, original)] for original in _references(snapshot)
    }
    values["snapshot_json"] = row["snapshot_json"]


def remap_study_parameters(parameters: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    identifier = parameters.get("design_revision_id")
    if isinstance(identifier, str):
        try:
            canonical = str(UUID(identifier))
        except ValueError:
            return parameters
        if canonical in id_map:
            return {**parameters, "design_revision_id": id_map[canonical]}
    return parameters
