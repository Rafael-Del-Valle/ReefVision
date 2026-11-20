"""Portable, project-scoped QC audit history and durable retry identities."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ReviewQueue,
    ReviewQueueBulkRequestRecord,
    ReviewQueueItemEvent,
    WorkflowGraphRecord,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.review_queue_events import ReviewQueueEventCreate
from reefvision.schemas.review_queues import ReviewQueueBulkRequest
from reefvision.services.frozen_dataset_integrity_16 import validate_frozen_dataset_manifest
from reefvision.services.workflow_review_queue_integrity import (
    queue_item_evidence_sha256,
    queue_reference_payload,
    validate_saved_queue_snapshot,
)
from reefvision.storage.datasets import canonical_json_sha256

FORMAT = "1.6"
QC_FORMATS = {FORMAT, "1.7", "1.7.1"}
EVENTS = "review_queue_item_events"
BULK = "review_queue_bulk_requests"
SECTIONS = (EVENTS, BULK)
Rows = dict[str, list[dict[str, Any]]]


def is_qc_graph(graph: Mapping[str, Any]) -> bool:
    return any(
        isinstance(n, dict) and n.get("node_type") == "qc_review_queue"
        for n in graph.get("nodes", ())
    )


def has_qc_history(session: Session, project_id: str) -> bool:
    if any(
        session.scalar(select(model.id).where(model.project_id == project_id).limit(1))
        for model in (ReviewQueueItemEvent, ReviewQueueBulkRequestRecord)
    ):
        return True
    graphs: Iterable[dict[str, Any]] = session.scalars(
        select(WorkflowGraphRecord.graph_json).where(WorkflowGraphRecord.project_id == project_id)
    )
    return any(is_qc_graph(graph) for graph in graphs)


def _uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected canonical UUID")
    return value


def _request_keys(operation: str, items: Sequence[str], legacy: bool = False) -> dict[str, str]:
    primary = min(items)
    return {
        item: operation if item == primary and not legacy else str(uuid5(UUID(operation), item))
        for item in items
    }


def _bulk_members(
    request: dict[str, Any], entries: Mapping[tuple[str, str], dict[str, Any]]
) -> dict[str, str]:
    """Match the marker or the older UUIDv5 form written by historical QC."""
    operation, items = request["id"], request["item_ids_json"]
    for legacy in (False, True):
        keys = _request_keys(operation, items, legacy)
        selected = {i: entries.get((i, key)) for i, key in keys.items()}
        if all(
            e is not None
            and e["review_queue_id"] == request["review_queue_id"]
            and e["event_type"] == "triage_" + request["action"]
            and e["actor"] == request["actor"]
            and e["comment"] == request["reason"]
            and e["assignee"] is None
            for e in selected.values()
        ):
            return {e["id"]: i for i, e in selected.items() if e is not None}
    raise ValidationError("QC bulk request has missing or inconsistent item audit evidence")


def _workflow_owners(rows: Rows) -> dict[str, dict[str, Any]]:
    return {
        f"workflow:{node['workflow_run_id']}:{node['id']}": node
        for node in rows.get("workflow_node_runs", [])
        if node.get("node_type") == "qc_review_queue"
    }


def validate_qc_exchange(version: str, project: str, rows: Rows) -> None:
    try:
        present = any(rows.get(s) for s in SECTIONS) or any(
            is_qc_graph(row["graph_json"]) for row in rows.get("workflow_graphs", ())
        )
        if version not in QC_FORMATS:
            if present:
                raise ValidationError("QC audit records require Project Exchange 1.6")
            return
        if not present and version != FORMAT:
            return
        if not present or not all(s in rows for s in SECTIONS):
            raise ValidationError("Project Exchange 1.6 is missing the QC history inventory")
        _validate_history(project, rows)
        versions = {v["id"]: v for v in rows.get("dataset_versions", [])}
        required = frozen_qc_dataset_ids(rows)
        items: dict[str, list[DatasetVersionItem]] = defaultdict(list)
        for item in rows.get("dataset_version_items", []):
            if item["dataset_version_id"] in required:
                items[item["dataset_version_id"]].append(DatasetVersionItem(**item))
        for identifier in required:
            version_row = versions[identifier]
            if version_row["project_id"] != project:
                raise ValidationError("Frozen QC dataset belongs to another project")
            validate_frozen_dataset_manifest(DatasetVersion(**version_row), items[identifier])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValidationError(
            "QC history contains an invalid request, event or workflow reference"
        ) from exc


def frozen_qc_dataset_ids(rows: Rows) -> set[str]:
    ids = {
        q["dataset_version_id"]
        for q in rows.get("review_queues", ())
        if q.get("dataset_version_id")
    }
    for row in rows.get("workflow_graphs", ()):
        graph = row["graph_json"]
        if is_qc_graph(graph):
            ids.update(
                node["parameters"]["dataset_version_id"]
                for node in graph["nodes"]
                if node.get("node_type") == "dataset_version_source"
                and (node.get("parameters") or {}).get("dataset_version_id")
            )
    return ids


def _validate_history(project: str, rows: Rows) -> None:
    queues = {q["id"]: q for q in rows.get("review_queues", [])}
    items = {i["id"]: i for i in rows.get("review_queue_items", [])}
    by_queue: dict[str, list[Any]] = defaultdict(list)
    for item in items.values():
        by_queue[item["review_queue_id"]].append(SimpleNamespace(**item))
    events: dict[tuple[str, str], dict[str, Any]] = {}
    for event in rows[EVENTS]:
        item, queue, key = (
            items[event["review_queue_item_id"]],
            queues[event["review_queue_id"]],
            _uuid(event["client_request_id"]),
        )
        pair = (item["id"], key)
        if (
            pair in events
            or queue["id"] != item["review_queue_id"]
            or any(e["project_id"] != project for e in (item, queue, event))
        ):
            raise ValidationError(
                "QC event has a duplicated request or inconsistent queue ownership"
            )
        kind = event["event_type"]
        if kind in ("assign", "unassign", "comment"):
            value = ReviewQueueEventCreate.model_validate(event)
            if (value.actor, value.comment, value.assignee) != (
                event["actor"],
                event["comment"],
                event["assignee"],
            ):
                raise ValueError("Invalid coordination labels")
        else:
            if not kind.startswith("triage_") or event["assignee"] is not None:
                raise ValueError("Unknown triage event")
            _validate_action(
                kind.removeprefix("triage_"), event["actor"], event["comment"], [item["id"]], key
            )
        events[pair] = event
    bound: set[str] = set()
    for request in rows[BULK]:
        members = request["item_ids_json"]
        _validate_action(
            request["action"], request["actor"], request["reason"], members, _uuid(request["id"])
        )
        if (
            request["project_id"] != project
            or len(set(members)) != len(members)
            or any(items[i]["review_queue_id"] != request["review_queue_id"] for i in members)
        ):
            raise ValidationError("QC bulk selection crosses project or queue boundaries")
        evidence = _bulk_members(request, events)
        if bound.intersection(evidence):
            raise ValidationError("Multiple QC requests claim the same audit event")
        bound.update(evidence)

    owners = _workflow_owners(rows)
    outputs = {a["id"]: a for a in rows.get("workflow_artifacts", [])}
    datasets = {d["id"]: d for d in rows.get("dataset_versions", [])}
    owned = {}
    for q in queues.values():
        producer = owners.get(q["created_by"])
        if producer is None and not q["input_checksums_json"].get("integrity_schema_version"):
            continue
        validate_saved_queue_snapshot(SimpleNamespace(**q), by_queue[q["id"]])
        if producer is None:
            continue
        if producer["id"] in owned:
            raise ValidationError("Multiple queues claim the same workflow producer")
        owned[producer["id"]] = q["id"]
        if producer["status"] == "succeeded":
            [identifier] = producer["output_artifact_ids_json"]
            output = outputs[identifier]
            dataset = datasets[q["dataset_version_id"]] if q.get("dataset_version_id") else None
            if (
                output["producer_node_run_id"] != producer["id"]
                or output["data_type"] != "review_queue_reference"
                or output["payload_json"]
                != queue_reference_payload(
                    SimpleNamespace(**q),
                    producer["workflow_run_id"],
                    producer["id"],
                    dataset["manifest_sha256"] if dataset else None,
                )
            ):
                raise ValidationError("Saved QC workflow output differs from its source queue")
    if any(n["status"] == "succeeded" and n["id"] not in owned for n in owners.values()):
        raise ValidationError("Saved QC workflow is missing its original queue")


def _validate_action(
    action: str, actor: str, reason: str | None, members: list[str], key: str
) -> None:
    model = ReviewQueueBulkRequest.model_validate(
        dict(
            action=action,
            actor=actor,
            reason=reason,
            item_ids=members,
            client_request_id=key,
            review_confirmed=action == "complete",
        )
    )
    if (
        model.actor != actor
        or model.reason != reason
        or (action == "skip" and not reason)
        or (action != "skip" and reason is not None)
    ):
        raise ValueError("Invalid stored triage description")


def remap_event_requests(rows: Rows, mapping: dict[str, str]) -> dict[str, str]:
    # A tied queue is ranked by image UUID. Keep that relative order using
    # fresh, independent UUIDs so both the copied and replayed ranking agree.
    images = sorted(r["id"] for r in rows.get("images", []))
    mapping.update(zip(images, sorted(mapping[i] for i in images), strict=True))
    events = {(e["review_queue_item_id"], e["client_request_id"]): e for e in rows.get(EVENTS, [])}
    mapped = {e["id"]: e["client_request_id"] for e in events.values()}
    for request in rows.get(BULK, []):
        source = _bulk_members(request, events)
        keys = _request_keys(mapping[request["id"]], [mapping[i] for i in request["item_ids_json"]])
        mapped.update({e: keys[mapping[i]] for e, i in source.items()})
    return mapped


def restore_qc_row(
    name: str,
    row: dict[str, Any],
    values: dict[str, Any],
    mapping: dict[str, str],
    event_requests: dict[str, str],
) -> None:
    if name == EVENTS:
        values.update(
            client_request_id=event_requests[row["id"]],
            actor=row["actor"],
            comment=row["comment"],
            assignee=row["assignee"],
        )
    elif name == BULK:
        values.update(
            actor=row["actor"],
            reason=row["reason"],
            item_ids_json=sorted(mapping[i] for i in row["item_ids_json"]),
        )
    elif name == "review_queue_items":
        values.update(reason_summary=row["reason_summary"], skip_reason=row["skip_reason"])
    elif name == "review_queues":
        creator = row["created_by"]
        parts = creator.split(":")
        if (
            len(parts) == 3
            and parts[0] == "workflow"
            and parts[1] in mapping
            and parts[2] in mapping
        ):
            creator = f"workflow:{mapping[parts[1]]}:{mapping[parts[2]]}"
        values["created_by"] = creator


def restore_scoring_proof(queue: ReviewQueue, items: Sequence[Any], source: dict[str, Any]) -> None:
    if "scoring_provenance_sha256" not in source:
        return
    scoring = {
        "formula_id": queue.formula_id,
        "formula_version": queue.formula_version,
        "configuration": queue.configuration_json,
    }
    version = source.get("integrity_schema_version")
    if version == "qc-review-queue-v3":
        scoring["integrity_schema_version"] = version
    queue.input_checksums_json = {
        **source,
        **queue.input_checksums_json,
        "scoring_provenance_sha256": canonical_json_sha256(scoring),
        "item_evidence_sha256": queue_item_evidence_sha256(items),
    }
    validate_saved_queue_snapshot(queue, items)
