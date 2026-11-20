"""Preserve and validate biological condition evidence in project exchange."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from typing import Any
from uuid import UUID

from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.spatial_condition_v14 import (
    ConditionObservation,
    ConditionReport,
    ConditionRevision,
)
from reefvision.services.spatial_condition_v14 import (
    CONDITION_CONTENT_FIELDS,
    condition_content_sha256,
    condition_next_phase,
    condition_resolved_label,
)
from reefvision.storage.datasets import canonical_json_sha256


def validate_condition_exchange(
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
    assets: dict[str, dict[str, Any]],
) -> None:
    metadata = {row["id"]: row for row in sections.get("spatial_asset_metadata_revisions", [])}
    rubrics: dict[tuple[str, str], str] = {}
    for rubric in sections.get("spatial_condition_rubrics", []):
        rubric_id, version = rubric.get("rubric_id"), rubric.get("version")
        digest = rubric.get("content_sha256")
        if (
            rubric.get("project_id") != project_id
            or not isinstance(rubric_id, str)
            or not 1 <= len(rubric_id) <= 128
            or not isinstance(version, str)
            or not 1 <= len(version) <= 128
            or not isinstance(digest, str)
            or len(digest) != 64
            or (rubric_id, version) in rubrics
        ):
            raise ValidationError("Condition exchange rubric declaration is invalid")
        rubrics[rubric_id, version] = digest

    revisions: dict[str, ConditionRevision] = {}
    for row in sections.get("spatial_condition_revisions", []):
        observation = row.get("observation_json")
        asset = assets.get(str(row.get("asset_id")))
        try:
            if (
                row.get("project_id") != project_id
                or asset is None
                or condition_content_sha256(row) != row.get("content_sha256")
            ):
                raise ValueError("invalid project, asset or condition digest")
            revision = ConditionRevision.model_validate(
                {
                    **row,
                    "observation": observation,
                    "decision": row.get("decision_json"),
                    "resolved_label": None,
                    "stale_source_metadata": False,
                }
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(
                "Condition exchange evidence failed integrity validation"
            ) from exc
        label_rubric = revision.observation.rubric
        key = (label_rubric.rubric_id, label_rubric.version)
        if rubrics.get(key) != canonical_json_sha256(label_rubric.model_dump(mode="json")):
            raise ValidationError("Condition exchange evidence lacks its frozen rubric")
        metadata_id = revision.observation.metadata_revision_id
        if (
            revision.observation.source_sha256 != asset["sha256"]
            or (
                metadata_id is not None
                and metadata.get(str(metadata_id), {}).get("spatial_source_asset_id") != asset["id"]
            )
            or str(revision.id) in revisions
        ):
            raise ValidationError("Condition exchange evidence has an invalid source binding")
        revisions[str(revision.id)] = revision

    parents: set[str] = set()
    for revision in revisions.values():
        if revision.phase == "observation":
            if (
                revision.previous_revision_id is not None
                or revision.decision is not None
                or revision.observation_id != revision.id
            ):
                raise ValidationError("Condition exchange observation ancestry is invalid")
            continue
        parent_id = str(revision.previous_revision_id)
        parent = revisions.get(parent_id)
        root = revisions.get(str(revision.observation_id))
        try:
            if (
                parent_id in parents
                or parent is None
                or root is None
                or root.phase != "observation"
                or parent.observation_id != root.id
                or parent.asset_id != revision.asset_id
                or parent.observation != revision.observation
                or root.observation != revision.observation
                or revision.decision is None
                or revision.phase
                != condition_next_phase(parent, revision.decision, parent.decision)
            ):
                raise ValueError("invalid condition history")
        except (ConflictError, ValueError) as exc:
            raise ValidationError("Condition exchange decision ancestry is invalid") from exc
        parents.add(parent_id)

    _validate_condition_reports(sections, revisions)


def _validate_condition_reports(
    sections: dict[str, list[dict[str, Any]]],
    revisions: dict[str, ConditionRevision],
) -> None:
    nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
    runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    graphs = {row["id"]: row for row in sections.get("workflow_graphs", [])}
    for artifact in sections.get("workflow_artifacts", []):
        if artifact.get("data_type") != "spatial_condition_report":
            continue
        try:
            payload = artifact["payload_json"]
            if canonical_json_sha256(payload) != artifact["payload_sha256"]:
                raise ValueError("checksum mismatch")
            report = ConditionReport.model_validate(payload)
            current = revisions[str(report.revision_id)]
            producer = nodes[artifact["producer_node_run_id"]]
            run = runs[artifact["workflow_run_id"]]
            graph = graphs[run["workflow_graph_record_id"]]
            [declared_node] = [
                node
                for node in graph["graph_json"]["nodes"]
                if node["node_id"] == producer["node_id"]
            ]
            parameters = {"asset_id": current.asset_id, "revision_id": current.id}
            if (
                artifact["producer_port_id"] != "report"
                or producer["status"] != "succeeded"
                or producer["node_type"] != "spatial_condition_report"
                or producer["workflow_run_id"] != run["id"]
                or declared_node["node_type"] != producer["node_type"]
                or any(
                    UUID(config[key]) != value
                    for config in (declared_node["parameters"], producer["parameters_json"])
                    for key, value in parameters.items()
                )
            ):
                raise ValueError("producer binding mismatch")

            # Saved execution requires then-current metadata. Later metadata revisions
            # affect live eligibility but cannot rewrite a historical artifact.
            chain = []
            while True:
                created_at = current.created_at
                chain.append(
                    current.model_copy(
                        update={
                            "created_at": (
                                created_at.replace(tzinfo=UTC)
                                if created_at.tzinfo is None
                                else created_at.astimezone(UTC)
                            ),
                            "resolved_label": condition_resolved_label(
                                current.observation, current.decision
                            ),
                        }
                    )
                )
                if current.previous_revision_id is None:
                    break
                current = revisions[str(current.previous_revision_id)]
            expected = ConditionReport(revision_id=report.revision_id, revisions=chain[::-1])
            if payload != expected.model_dump(mode="json"):
                raise ValueError("ledger snapshot mismatch")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(
                "Condition workflow report does not match its saved producer and ledger"
            ) from exc


def remap_condition_observation(
    evidence: Mapping[str, Any], id_map: Mapping[str, str]
) -> dict[str, Any]:
    observation = ConditionObservation.model_validate(evidence)
    payload = observation.model_dump(mode="json")
    metadata_id = observation.metadata_revision_id
    if metadata_id is not None:
        payload["metadata_revision_id"] = id_map[str(metadata_id)]
    return payload


def remap_condition_report(payload: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    report = {**payload, "revision_id": id_map[payload["revision_id"]], "revisions": []}
    id_fields = set(CONDITION_CONTENT_FIELDS) - {"phase", "observation_json", "decision_json"}
    for revision in payload["revisions"]:
        moved = {
            **revision,
            **{
                key: id_map[revision[key]] if revision[key] is not None else None
                for key in id_fields
            },
            "observation": remap_condition_observation(revision["observation"], id_map),
        }
        moved["content_sha256"] = condition_content_sha256(
            {**moved, "observation_json": moved["observation"], "decision_json": moved["decision"]}
        )
        report["revisions"].append(moved)
    return report
