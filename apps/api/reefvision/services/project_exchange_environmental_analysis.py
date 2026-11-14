"""Validate and remap immutable composite environmental-analysis evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.services.scientific_data import content_hash

ANALYSIS_SECTIONS = {
    "environmental_analysis_definitions",
    "environmental_analysis_results",
}
ANALYSIS_KINDS = {
    "lunar_context",
    "tidal_context",
    "event_window",
    "observation_environment_join",
    "lagged_comparison",
    "current_streamline",
}
WORKFLOW_NODE_BY_KIND = {
    "lunar_context": "lunar_context_analysis",
    "tidal_context": "tidal_context_analysis",
    "event_window": "event_window_analysis",
    "observation_environment_join": "observation_environment_join",
    "lagged_comparison": "lagged_comparison",
    "current_streamline": "current_streamline_analysis",
}


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _definition_content(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_kind": row["analysis_kind"],
        "name": row["name"],
        "configuration": row["configuration_json"],
        "calculation_version": row["calculation_version"],
    }


def _result_content(row: dict[str, Any], definition_sha256: str) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "definition_id": row["definition_id"],
        "definition_sha256": definition_sha256,
        "analysis_kind": row["analysis_kind"],
        "observed_at": _utc(row["observed_at"]).isoformat(),
        "payload": row["payload_json"],
        "input_snapshot": row["input_snapshot_json"],
        "source_record_ids": row["source_record_ids_json"],
        "source_analysis_result_ids": row["source_analysis_result_ids_json"],
        "quality_control": row["quality_control_json"],
        "uncertainty": row.get("uncertainty_json"),
        "workflow_run_id": row.get("workflow_run_id"),
        "workflow_node_run_id": row.get("workflow_node_run_id"),
    }


def _lunar_payload_content(payload: dict[str, Any]) -> dict[str, Any]:
    content = {
        key: payload[key]
        for key in (
            "schema_version",
            "algorithm",
            "project_id",
            "observed_at",
            "phase",
            "phase_fraction",
            "illuminated_fraction",
            "approximate_lunar_age_days",
            "reference_frame",
            "computation",
        )
    }
    content["observed_at"] = _utc(payload["observed_at"]).isoformat()
    return content


def validate_environmental_analysis_exchange(
    project_id: str, sections: dict[str, list[dict[str, Any]]]
) -> None:
    try:
        _validate_environmental_analysis_exchange(project_id, sections)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError("Invalid environmental-analysis exchange structure") from exc


def _validate_environmental_analysis_exchange(
    project_id: str, sections: dict[str, list[dict[str, Any]]]
) -> None:
    definitions = {row["id"]: row for row in sections.get("environmental_analysis_definitions", [])}
    results = {row["id"]: row for row in sections.get("environmental_analysis_results", [])}
    if len(definitions) != len(sections.get("environmental_analysis_definitions", [])):
        raise ValidationError("Duplicate environmental analysis definition identifier")
    if len(results) != len(sections.get("environmental_analysis_results", [])):
        raise ValidationError("Duplicate environmental analysis result identifier")
    records = {row["id"] for row in sections.get("scientific_records", [])}
    events = {row["id"] for row in sections.get("environmental_event_definitions", [])}
    workflow_runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    workflow_nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}

    for row in definitions.values():
        if (
            row.get("project_id") != project_id
            or row.get("analysis_kind") not in ANALYSIS_KINDS
            or not isinstance(row.get("configuration_json"), dict)
            or not isinstance(row.get("calculation_version"), str)
            or content_hash(_definition_content(row)) != row.get("definition_sha256")
        ):
            raise ValidationError("Environmental analysis definition checksum mismatch")
        config = row["configuration_json"]
        if (
            row["analysis_kind"] == "event_window"
            and config.get("event_definition_id") not in events
        ):
            raise ValidationError("Event-window analysis refers to a missing threshold definition")
        if row["analysis_kind"] == "observation_environment_join":
            observation_ids = config.get("observation_record_ids")
            if not isinstance(observation_ids, list) or any(
                identifier not in records for identifier in observation_ids
            ):
                raise ValidationError("Environmental join refers to missing observation records")
        if row["analysis_kind"] == "lagged_comparison":
            source = results.get(config.get("join_result_id"))
            if source is None or source.get("analysis_kind") != "observation_environment_join":
                raise ValidationError("Lagged analysis refers to a missing environmental join")
        if row["analysis_kind"] == "current_streamline":
            source_ids = config.get("scientific_record_ids")
            if not isinstance(source_ids, list) or any(
                identifier not in records for identifier in source_ids
            ):
                raise ValidationError("Current streamline refers to missing scientific records")

    for row in results.values():
        definition = definitions.get(row.get("definition_id"))
        if (
            row.get("project_id") != project_id
            or definition is None
            or row.get("analysis_kind") != definition.get("analysis_kind")
            or not isinstance(row.get("payload_json"), dict)
            or not isinstance(row.get("input_snapshot_json"), dict)
            or not isinstance(row.get("quality_control_json"), dict)
            or (
                row.get("uncertainty_json") is not None
                and not isinstance(row.get("uncertainty_json"), dict)
            )
        ):
            raise ValidationError("Environmental analysis result structure is invalid")
        source_record_ids = row.get("source_record_ids_json")
        source_result_ids = row.get("source_analysis_result_ids_json")
        if (
            not isinstance(source_record_ids, list)
            or len(source_record_ids) != len(set(source_record_ids))
            or any(identifier not in records for identifier in source_record_ids)
        ):
            raise ValidationError("Environmental analysis refers to missing scientific records")
        if (
            not isinstance(source_result_ids, list)
            or len(source_result_ids) != len(set(source_result_ids))
            or row["id"] in source_result_ids
            or any(identifier not in results for identifier in source_result_ids)
        ):
            raise ValidationError("Environmental analysis refers to missing source analyses")
        workflow_run_id = row.get("workflow_run_id")
        workflow_node_run_id = row.get("workflow_node_run_id")
        if (workflow_run_id is None) != (workflow_node_run_id is None):
            raise ValidationError("Environmental analysis workflow lineage is incomplete")
        if workflow_node_run_id is not None:
            node = workflow_nodes.get(workflow_node_run_id)
            if (
                workflow_run_id not in workflow_runs
                or node is None
                or node.get("workflow_run_id") != workflow_run_id
                or node.get("node_type") != WORKFLOW_NODE_BY_KIND[row["analysis_kind"]]
            ):
                raise ValidationError("Environmental analysis workflow lineage is invalid")
        if content_hash(_result_content(row, definition["definition_sha256"])) != row.get(
            "content_sha256"
        ):
            raise ValidationError("Environmental analysis result checksum mismatch")
        if row["analysis_kind"] == "lunar_context":
            payload = row["payload_json"]
            if payload.get("project_id") != project_id or content_hash(
                _lunar_payload_content(payload)
            ) != payload.get("content_sha256"):
                raise ValidationError("Lunar analysis payload checksum mismatch")
        if row["analysis_kind"] == "lagged_comparison":
            join_id = definition["configuration_json"]["join_result_id"]
            if source_result_ids != [join_id]:
                raise ValidationError("Lagged analysis source lineage mismatch")
            if definition["calculation_version"] == "reefvision-lagged-descriptive-comparison-2":
                snapshot = row["input_snapshot_json"]
                if snapshot.get("join_result_sha256") != results[join_id]["content_sha256"]:
                    raise ValidationError("Lagged analysis source result checksum mismatch")


def _remap_json(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_remap_json(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _remap_analysis_field(key, item, id_map) for key, item in value.items()}
    return value


def _remap_study_assignment(value: Any, id_map: dict[str, str]) -> Any:
    if value is None:
        return None
    record_id = value["observation_record_id"]
    return {**value, "observation_record_id": id_map.get(record_id, record_id)}


def remap_study_assignments(value: Any, id_map: dict[str, str]) -> Any:
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("observation_record_id"), str)
        for item in value
    ):
        return value
    return sorted(
        [_remap_study_assignment(assignment, id_map) for assignment in value],
        key=lambda assignment: assignment["observation_record_id"],
    )


def _remap_legacy_unit_id(value: str, id_map: dict[str, str]) -> str:
    kind, separator, identifier_and_frame = value.partition(":")
    if not separator or kind not in {"record", "image", "video"}:
        return value
    identifier, separator, frame = identifier_and_frame.partition(":")
    return f"{kind}:{id_map.get(identifier, identifier)}{separator}{frame}"


def _remap_analysis_field(key: str, value: Any, id_map: dict[str, str]) -> Any:
    if key == "study_assignment":
        return _remap_study_assignment(value, id_map)
    if key == "study_assignments":
        return remap_study_assignments(value, id_map)
    if key == "environmental_record_reuse_counts":
        return {id_map.get(identifier, identifier): count for identifier, count in value.items()}
    if key == "independent_unit_id":
        return _remap_legacy_unit_id(value, id_map)
    if key == "independent_unit_reuse_counts":
        return {
            _remap_legacy_unit_id(identifier, id_map): count for identifier, count in value.items()
        }
    if key == "experimental_unit_reuse_counts":
        return value
    return _remap_json(value, id_map)


def remap_environmental_analysis_sections(
    sections: dict[str, list[dict[str, Any]]], id_map: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    definitions = deepcopy(sections.get("environmental_analysis_definitions", []))
    results = deepcopy(sections.get("environmental_analysis_results", []))
    definition_hashes: dict[str, str] = {}
    for row in definitions:
        old_id = row["id"]
        row["id"] = id_map[old_id]
        row["project_id"] = id_map[row["project_id"]]
        row["configuration_json"] = _remap_json(row["configuration_json"], id_map)
        row["definition_sha256"] = content_hash(_definition_content(row))
        definition_hashes[row["id"]] = row["definition_sha256"]
    for row in results:
        row["id"] = id_map[row["id"]]
        row["project_id"] = id_map[row["project_id"]]
        row["definition_id"] = id_map[row["definition_id"]]
        workflow_run_id = row.get("workflow_run_id")
        if isinstance(workflow_run_id, str):
            row["workflow_run_id"] = id_map.get(workflow_run_id, workflow_run_id)
        workflow_node_run_id = row.get("workflow_node_run_id")
        if isinstance(workflow_node_run_id, str):
            row["workflow_node_run_id"] = id_map.get(workflow_node_run_id, workflow_node_run_id)
        row["source_record_ids_json"] = [
            id_map[identifier] for identifier in row["source_record_ids_json"]
        ]
        row["source_analysis_result_ids_json"] = [
            id_map[identifier] for identifier in row["source_analysis_result_ids_json"]
        ]
        for field in (
            "payload_json",
            "input_snapshot_json",
            "quality_control_json",
            "uncertainty_json",
        ):
            row[field] = _remap_json(row.get(field), id_map)
        if row["analysis_kind"] == "lunar_context":
            row["payload_json"]["content_sha256"] = content_hash(
                _lunar_payload_content(row["payload_json"])
            )
    # A lag's source hash refers to the remapped join, regardless of archive order.
    result_by_id = {row["id"]: row for row in results}
    for row in results:
        if row["analysis_kind"] == "lagged_comparison":
            continue
        row["content_sha256"] = content_hash(
            _result_content(row, definition_hashes[row["definition_id"]])
        )
    for row in results:
        if row["analysis_kind"] != "lagged_comparison":
            continue
        join_id = row["source_analysis_result_ids_json"][0]
        row["input_snapshot_json"]["join_result_sha256"] = result_by_id[join_id]["content_sha256"]
        row["content_sha256"] = content_hash(
            _result_content(row, definition_hashes[row["definition_id"]])
        )
    return {
        "environmental_analysis_definitions": definitions,
        "environmental_analysis_results": results,
    }
