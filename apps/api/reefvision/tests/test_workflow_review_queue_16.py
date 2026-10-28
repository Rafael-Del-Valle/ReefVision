"""ReefVision 1.6 QC queue workflow and standalone API regression."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ReviewQueue,
    ReviewQueueItem,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.services.workflow_review_queue_integrity import (
    V3_SUPPORTED_SIGNALS,
    queue_item_evidence_sha256,
    validate_saved_queue_snapshot,
)
from reefvision.services.workflow_runtime_adapters import execute_runtime_adapter
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one


def _graph() -> dict[str, object]:
    return {
        "graph_id": "qc-review-queue-16",
        "name": "QC review queue",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }


@pytest.mark.parametrize("corruption", ["payload", "checksum"])
def test_qc_queue_adapter_rejects_modified_project_source_artifact(corruption: str) -> None:
    """A persisted source reference must retain its original payload digest."""
    payload = {"project_id": "project-one"}
    source = SimpleNamespace(
        data_type="project_reference",
        payload_json=dict(payload),
        payload_sha256=canonical_json_sha256(payload),
    )
    if corruption == "payload":
        source.payload_json = {**payload, "unreviewed_override": True}
    else:
        source.payload_sha256 = "0" * 64
    with pytest.raises(ValidationError, match="source artifact failed integrity"):
        create_review_queue_workflow_artifact(
            session=cast(Session, None),
            settings=cast(Settings, None),
            project_id="project-one",
            parameters={},
            inputs={"project": [cast(WorkflowArtifact, source)]},
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong_port",
        "wrong_producer",
        "wrong_binding",
        "unfinished_producer",
        "missing_producer_output",
        "substituted_producer_output",
    ],
)
def test_qc_queue_adapter_requires_bound_completed_source(corruption: str) -> None:
    """Even a correctly signed source must belong to the saved graph edge."""
    payload = {"project_id": "project-one"}
    source = SimpleNamespace(
        id="artifact",
        workflow_run_id="run",
        producer_node_run_id="producer",
        producer_port_id="project",
        data_type="project_reference",
        payload_json=payload,
        payload_sha256=canonical_json_sha256(payload),
    )
    run = SimpleNamespace(project_id="project-one")
    node = SimpleNamespace(
        workflow_run_id="run",
        node_type="qc_review_queue",
        input_artifact_ids_json=["artifact"],
    )
    producer = SimpleNamespace(
        workflow_run_id="run",
        node_type="project_source",
        status="succeeded",
        output_artifact_ids_json=["artifact"],
    )
    if corruption == "wrong_port":
        source.producer_port_id = "unreviewed_project"
    elif corruption == "wrong_producer":
        source.producer_node_run_id = "qc"
    elif corruption == "wrong_binding":
        node.input_artifact_ids_json = ["another-artifact"]
    elif corruption == "unfinished_producer":
        producer.status = "pending"
    elif corruption == "missing_producer_output":
        producer.output_artifact_ids_json = []
    else:
        producer.output_artifact_ids_json = ["another-artifact"]

    class ReadOnlySession:
        def get(self, model: object, identifier: str) -> object | None:
            if model is WorkflowRun:
                return run if identifier == "run" else None
            if model is WorkflowNodeRun:
                return {"qc": node, "producer": producer}.get(identifier)
            raise AssertionError("Invalid source must be rejected before any queue access")

    with pytest.raises(ValidationError, match="producer or binding provenance"):
        create_review_queue_workflow_artifact(
            session=cast(Session, ReadOnlySession()),
            settings=cast(Settings, None),
            project_id="project-one",
            parameters={"__workflow_run_id": "run", "__workflow_node_run_id": "qc"},
            inputs={"project": [cast(WorkflowArtifact, source)]},
        )


def test_qc_queue_standalone_and_saved_workflow_share_service(client: TestClient) -> None:
    project = create_project(client, "QC review workflow")
    imported = import_one(
        client,
        project["id"],
        filename="qc-review-workflow.png",
        relative_path="qc-review/workflow.png",
    )
    assert len(imported["successful"]) == 1

    standalone = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    assert standalone.json()["item_count"] == 1
    assert len(standalone.json()["input_checksums_json"]["scoring_provenance_sha256"]) == 64
    assert len(standalone.json()["input_checksums_json"]["item_evidence_sha256"]) == 64
    assert standalone.json()["input_checksums_json"]["integrity_schema_version"] == (
        "qc-review-queue-v3"
    )

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(x for x in registry.json() if x["node_type"] == "qc_review_queue")
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["review_queue_reference"]

    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=_graph())
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]

    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": _graph()},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run = queued.json()
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(run["job_id"]),
        )
        is True
    )

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["run"]["status"] == "succeeded"
    outputs = [
        item for item in payload["artifacts"] if item["data_type"] == "review_queue_reference"
    ]
    assert len(outputs) == 1
    result = outputs[0]["payload_json"]
    assert result["item_count"] == 1
    assert result["priority_score_unit"] == "dimensionless"
    assert result["review_status"] == "requires_researcher_review"
    assert result["workflow_run_id"] == run["id"]
    assert len(outputs[0]["payload_sha256"]) == 64
    response = client.get(f"/api/v1/review-queues/{result['queue_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["created_by"].startswith("workflow:")
    # The executable saved graph must persist a meaningful scoring
    # normalization, not merely a well-formed queue reference.
    persisted_weights = response.json()["configuration_json"]["weights"]
    assert result["input_checksums"]["integrity_schema_version"] == "qc-review-queue-v3"
    assert set(persisted_weights) == V3_SUPPORTED_SIGNALS
    assert sum(persisted_weights.values()) > 0
    assert all(value >= 0 for value in persisted_weights.values())
    assert len(response.json()["input_checksums_json"]["scoring_provenance_sha256"]) == 64
    assert len(response.json()["input_checksums_json"]["item_evidence_sha256"]) == 64

    item_id = client.get(f"/api/v1/review-queues/{result['queue_id']}/items").json()["items"][0][
        "id"
    ]
    event_url = f"/api/v1/review-queues/{result['queue_id']}/items/{item_id}/events"
    comment_payload = {
        "client_request_id": str(uuid4()),
        "event_type": "comment",
        "actor": "researcher",
        "comment": "Review this saved workflow image",
    }
    comment = client.post(event_url, json=comment_payload)
    assert comment.status_code == 201, comment.text

    # The saved executable graph's review queue must not accept a replay of
    # manually authored coordination evidence assigned to another project.
    # The API cannot repair history; this deliberate corruption is test-only.
    unrelated = create_project(client, "Foreign saved QC comment provenance")
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, comment.json()["id"])
        assert event is not None
        event.project_id = unrelated["id"]
        session.commit()
    rejected_comment_retry = client.post(event_url, json=comment_payload)
    assert rejected_comment_retry.status_code == 409, rejected_comment_retry.text
    assert client.get(event_url).status_code == 409
    # Even an unrelated new comment must not append evidence to a saved
    # Workflow Builder review queue while prior provenance is inconsistent.
    blocked_new_comment = client.post(
        event_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "researcher",
            "comment": "Second review note while history is corrupted",
        },
    )
    assert blocked_new_comment.status_code == 409, blocked_new_comment.text
    # The same saved, typed QC reference must not be triaged by a new bulk
    # request while its manually reviewed audit history has foreign provenance.
    blocked_bulk = client.post(
        f"/api/v1/review-queues/{result['queue_id']}/items/bulk",
        json={
            "item_ids": [item_id],
            "action": "start",
            "actor": "workflow reviewer",
            "client_request_id": str(uuid4()),
        },
    )
    assert blocked_bulk.status_code == 409, blocked_bulk.text
    unchanged_item = client.get(f"/api/v1/review-queues/{result['queue_id']}/items").json()[
        "items"
    ][0]
    assert unchanged_item["review_state"] == "pending"
    with app.state.session_factory() as session:
        assert (
            session.query(ReviewQueueItemEvent).filter_by(review_queue_item_id=item_id).count() == 1
        )
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, comment.json()["id"])
        assert event is not None
        assert event.project_id == unrelated["id"]
        event.project_id = project["id"]
        session.commit()
    recovered_comment_retry = client.post(event_url, json=comment_payload)
    assert recovered_comment_retry.status_code == 201, recovered_comment_retry.text
    assert recovered_comment_retry.json()["id"] == comment.json()["id"]
    assert client.get(event_url).json()["total"] == 1

    # A manually triaged item produced by a saved executable workflow keeps
    # its queue reference, scientific evidence and researcher-review gate.
    keyed_start = {
        "item_ids": [item_id],
        "action": "start",
        "actor": "workflow reviewer",
        "client_request_id": str(uuid4()),
    }
    triaged = client.post(
        f"/api/v1/review-queues/{result['queue_id']}/items/bulk",
        json=keyed_start,
    )
    assert triaged.status_code == 200, triaged.text
    assert triaged.json()["changed_count"] == 1
    assert triaged.json()["requires_researcher_review"] is True
    history = client.get(event_url).json()
    assert history["total"] == 2
    assert history["items"][1]["event_type"] == "triage_start"
    assert history["items"][1]["actor"] == "workflow reviewer"

    # A saved executable QC graph and its typed review-required artifact must
    # tolerate manual single-item state transitions without losing audit history
    # or changing immutable scientific evidence on a retry.
    skipped = client.post(
        f"/api/v1/review-queue-items/{item_id}/skip",
        json={"reason": "Verify uncertain octocoral boundary"},
    )
    assert skipped.status_code == 200, skipped.text
    # Replaying the original saved-workflow queue triage must not override a
    # subsequent scientist's decision or duplicate the original audit event.
    replayed_start = client.post(
        f"/api/v1/review-queues/{result['queue_id']}/items/bulk",
        json=keyed_start,
    )
    assert replayed_start.status_code == 200, replayed_start.text
    assert replayed_start.json()["changed_count"] == 0
    assert replayed_start.json()["items"][0]["review_state"] == "skipped"
    assert replayed_start.json()["requires_researcher_review"] is True
    assert client.get(event_url).json()["total"] == 3
    returned = client.post(f"/api/v1/review-queue-items/{item_id}/return")
    assert returned.status_code == 200, returned.text
    history = client.get(event_url).json()
    assert history["total"] == 4
    assert [event["event_type"] for event in history["items"]] == [
        "comment",
        "triage_start",
        "triage_skip",
        "triage_return",
    ]
    assert history["items"][2]["comment"] == "Verify uncertain octocoral boundary"
    assert history["items"][2]["actor"] == "local_user"
    assert history["items"][3]["actor"] == "local_user"

    # Completing a queue item is an audited triage transition, not acceptance
    # of a model prediction or an annotation. Saved workflow retries must
    # preserve this manual history and the researcher-review gate.
    restarted = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    assert restarted.status_code == 200, restarted.text
    completed = client.post(
        f"/api/v1/review-queues/{result['queue_id']}/items/bulk",
        json={
            "item_ids": [item_id],
            "action": "complete",
            "actor": "workflow reviewer",
            "review_confirmed": True,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["changed_count"] == 1
    assert completed.json()["items"][0]["review_state"] == "completed"
    assert completed.json()["requires_researcher_review"] is True
    assert client.post(f"/api/v1/review-queue-items/{item_id}/complete").status_code == 409
    history = client.get(event_url).json()
    assert history["total"] == 6
    assert history["items"][-2]["event_type"] == "triage_start"
    assert history["items"][-1]["event_type"] == "triage_complete"
    assert history["items"][-1]["actor"] == "workflow reviewer"
    assert history["requires_researcher_review"] is True

    with app.state.session_factory() as session:
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run["id"],
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        assert source is not None
        qc_node = next(item for item in payload["nodes"] if item["node_id"] == "qc")
        persisted_node = session.get(WorkflowNodeRun, qc_node["id"])
        assert persisted_node is not None
        assert persisted_node.node_type == "qc_review_queue"
        saved_parameters = dict(persisted_node.parameters_json or {})
        assert "source_quality_control_run_id" in saved_parameters
        assert "review_below_confidence" in saved_parameters
        params = {
            **saved_parameters,
            "__workflow_run_id": run["id"],
            "__workflow_node_run_id": qc_node["id"],
        }
        # Source references are immutable typed workflow evidence. Even when
        # the project identity is unchanged, a modified payload or checksum
        # must fail before an existing human-reviewed queue can be replayed.
        original_source_payload = dict(source.payload_json)
        original_source_digest = source.payload_sha256
        source.payload_json = {**original_source_payload, "unreviewed_override": True}
        session.flush()
        with pytest.raises(ValidationError, match="source artifact failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        source.payload_json = original_source_payload
        source.payload_sha256 = "0" * 64
        session.flush()
        with pytest.raises(ValidationError, match="source artifact failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        source.payload_sha256 = original_source_digest
        session.flush()
        # A valid JSON digest alone must not allow substitution of an
        # unbound or wrongly produced project reference on saved QC retry.
        for field, bad_value in (
            ("producer_port_id", "unreviewed_project"),
            ("producer_node_run_id", persisted_node.id),
        ):
            original = getattr(source, field)
            setattr(source, field, bad_value)
            session.flush()
            with pytest.raises(ValidationError, match="producer or binding provenance"):
                execute_runtime_adapter(
                    "qc_review_queue",
                    session=session,
                    settings=app.state.settings,
                    project_id=project["id"],
                    parameters=params,
                    inputs={"project": [source]},
                )
            setattr(source, field, original)
            session.flush()
        original_binding = list(persisted_node.input_artifact_ids_json)
        assert original_binding == [source.id]
        persisted_node.input_artifact_ids_json = []
        session.flush()
        with pytest.raises(ValidationError, match="producer or binding provenance"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        persisted_node.input_artifact_ids_json = original_binding
        producer = session.get(WorkflowNodeRun, source.producer_node_run_id)
        assert producer is not None and producer.status == "succeeded"
        producer.status = "pending"
        session.flush()
        with pytest.raises(ValidationError, match="producer or binding provenance"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        producer.status = "succeeded"
        session.flush()
        # A signed source also must appear in the producing node's saved
        # output list, not just claim that node as its producer.
        original_outputs = list(producer.output_artifact_ids_json)
        assert original_outputs == [source.id]
        for substituted_outputs in ([], ["another-artifact"]):
            producer.output_artifact_ids_json = substituted_outputs
            session.flush()
            with pytest.raises(ValidationError, match="producer or binding provenance"):
                execute_runtime_adapter(
                    "qc_review_queue",
                    session=session,
                    settings=app.state.settings,
                    project_id=project["id"],
                    parameters=params,
                    inputs={"project": [source]},
                )
        producer.output_artifact_ids_json = original_outputs
        session.flush()
        retry = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert retry[0]["payload"]["queue_id"] == result["queue_id"]
        # Persisted snapshots must fail closed on retry, not silently reuse
        # tampered scores even when workflow parameters are unchanged.
        saved_item = session.scalar(
            select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == result["queue_id"])
        )
        assert saved_item is not None
        original_score = saved_item.score
        saved_item.score = original_score + 1.0
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_item.score = original_score
        session.flush()
        # A persisted Workflow Builder retry must reject nonfinite raw
        # scientific signals even if the score itself is still finite.
        original_signals = saved_item.signal_values_json
        saved_item.signal_values_json = {
            **original_signals,
            "pending_proposals": float("nan"),
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_item.signal_values_json = original_signals
        session.flush()
        # A score-only checksum cannot detect a rewritten scientific
        # explanation. The full evidence digest must protect persisted signal
        # contributions while leaving reviewer decisions editable.
        original_breakdown = saved_item.score_breakdown_json
        assert original_breakdown
        saved_item.score_breakdown_json = [
            {**original_breakdown[0], "contribution": 999.0},
            *original_breakdown[1:],
        ]
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        # Even if a saved checksum is re-signed to match the modified
        # explanation, the persisted formula and scientific evidence must
        # agree before a saved Workflow Builder retry can reuse the queue.
        saved_queue = session.get(ReviewQueue, result["queue_id"])
        assert saved_queue is not None
        original_checksums = dict(saved_queue.input_checksums_json)
        saved_queue.input_checksums_json = {
            **original_checksums,
            "item_evidence_sha256": queue_item_evidence_sha256([saved_item]),
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.input_checksums_json = original_checksums
        saved_item.score_breakdown_json = original_breakdown
        session.flush()
        assert (
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )[0]["payload"]["queue_id"]
            == result["queue_id"]
        )
        # The request may omit a QC run even when the service resolves one.
        # A changed stored configuration must never silently alter provenance.
        saved_queue = session.get(ReviewQueue, result["queue_id"])
        assert saved_queue is not None
        original_config = dict(saved_queue.configuration_json)
        saved_queue.configuration_json = {
            **original_config,
            "source_quality_control_run_id": "other-qc-run",
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.configuration_json = original_config
        session.flush()
        # The executable saved graph must reject an impossible confidence
        # gate even when a modified scoring-provenance digest is re-signed.
        # Neither the review history nor the original QC scores are rewritten.
        original_checksums = dict(saved_queue.input_checksums_json)
        saved_queue.configuration_json = {
            **original_config,
            "review_below_confidence": 1.25,
        }
        saved_queue.input_checksums_json = {
            **original_checksums,
            "scoring_provenance_sha256": canonical_json_sha256(
                {
                    "formula_id": saved_queue.formula_id,
                    "formula_version": saved_queue.formula_version,
                    "configuration": saved_queue.configuration_json,
                }
            ),
        }
        session.flush()
        # The snapshot validator must reject an invalid re-signed scientific
        # threshold even when the saved workflow's earlier parameter-equality
        # guard would reject the retry first.
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            validate_saved_queue_snapshot(saved_queue, [saved_item])
        # Workflow replay must independently fail closed before any mutation;
        # its earlier retry-parameter guard is the expected error surface.
        with pytest.raises(ValidationError, match="retry parameters changed"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.configuration_json = original_config
        saved_queue.input_checksums_json = original_checksums
        session.flush()
        assert (
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )[0]["payload"]["queue_id"]
            == result["queue_id"]
        )
        # A persisted executable workflow must reject an invented biological
        # scoring signal even if the configuration digest is recomputed.
        # Historical v2 snapshots remain readable, but new v3 queues freeze
        # the full formula input set and keep reviewer decisions untouched.
        saved_queue.configuration_json = {
            **original_config,
            "weights": {
                **original_config["weights"],
                "unreviewed_species_bias": 0.0,
            },
        }
        saved_queue.input_checksums_json = {
            **original_checksums,
            "scoring_provenance_sha256": canonical_json_sha256(
                {
                    "formula_id": saved_queue.formula_id,
                    "formula_version": saved_queue.formula_version,
                    "configuration": saved_queue.configuration_json,
                    "integrity_schema_version": "qc-review-queue-v3",
                }
            ),
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.configuration_json = original_config
        saved_queue.input_checksums_json = original_checksums
        session.flush()
        assert (
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )[0]["payload"]["queue_id"]
            == result["queue_id"]
        )
        # A re-signed false raw pending-proposal count must not survive a
        # saved executable Workflow Builder retry, even if the score and
        # normalized component remain internally consistent.
        original_signals = dict(saved_item.signal_values_json)
        original_breakdown = list(saved_item.score_breakdown_json)
        original_checksums = dict(saved_queue.input_checksums_json)
        assert saved_item.normalized_signals_json["pending_proposals"] == 0.0
        saved_item.signal_values_json = {
            **original_signals,
            "pending_proposals": 5.0,
        }
        saved_item.score_breakdown_json = [
            {**part, "raw_value": 5.0} if part["signal_id"] == "pending_proposals" else part
            for part in original_breakdown
        ]
        saved_queue.input_checksums_json = {
            **original_checksums,
            "item_evidence_sha256": queue_item_evidence_sha256([saved_item]),
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        assert saved_item.review_state == "completed"
        saved_item.signal_values_json = original_signals
        saved_item.score_breakdown_json = original_breakdown
        saved_queue.input_checksums_json = original_checksums
        session.flush()
        assert (
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )[0]["payload"]["queue_id"]
            == result["queue_id"]
        )
        # Binary QC flags are yes/no scientific observations. Re-signing
        # a fractional raw flag with a matching breakdown must fail before
        # an interrupted saved workflow can reuse the completed review queue.
        original_signals = dict(saved_item.signal_values_json)
        original_breakdown = list(saved_item.score_breakdown_json)
        original_checksums = dict(saved_queue.input_checksums_json)
        for binary_signal in ("unreviewed_state", "missing_group_metadata"):
            saved_item.signal_values_json = {
                **original_signals,
                binary_signal: 0.5,
            }
            saved_item.score_breakdown_json = [
                {**part, "raw_value": 0.5} if part["signal_id"] == binary_signal else part
                for part in original_breakdown
            ]
            saved_queue.input_checksums_json = {
                **original_checksums,
                "item_evidence_sha256": queue_item_evidence_sha256([saved_item]),
            }
            session.flush()
            with pytest.raises(ValidationError, match="snapshot failed integrity"):
                execute_runtime_adapter(
                    "qc_review_queue",
                    session=session,
                    settings=app.state.settings,
                    project_id=project["id"],
                    parameters=params,
                    inputs={"project": [source]},
                )
            assert saved_item.review_state == "completed"
            saved_item.signal_values_json = original_signals
            saved_item.score_breakdown_json = original_breakdown
            saved_queue.input_checksums_json = original_checksums
            session.flush()
        assert (
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )[0]["payload"]["queue_id"]
            == result["queue_id"]
        )
        # The saved workflow must also reject altered scoring provenance,
        # even when the original item scores and scope checksum are intact.
        original_formula_version = saved_queue.formula_version
        saved_queue.formula_version = "unverified-scoring-version"
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.formula_version = original_formula_version
        session.flush()
        restored = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert restored[0]["payload"]["queue_id"] == result["queue_id"]
        # Re-signing a persisted digest cannot silently switch the scientific
        # scoring algorithm used by an executable saved workflow.
        saved_queue.formula_version = "99.0.0"
        saved_queue.input_checksums_json = {
            **original_checksums,
            "scoring_provenance_sha256": canonical_json_sha256(
                {
                    "formula_id": saved_queue.formula_id,
                    "formula_version": saved_queue.formula_version,
                    "configuration": saved_queue.configuration_json,
                }
            ),
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.formula_version = original_formula_version
        saved_queue.input_checksums_json = original_checksums
        session.flush()
        assert (
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )[0]["payload"]["queue_id"]
            == result["queue_id"]
        )
        # The saved scientific summary is independent of the scope checksum.
        # Reject tampering without changing reviewer decisions or live QC.
        original_summary = dict(saved_queue.summary_json)
        saved_queue.summary_json = {
            **original_summary,
            "average_score": original_summary["average_score"] + 1.0,
        }
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        saved_queue.summary_json = original_summary
        session.flush()
        restored = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert restored[0]["payload"]["queue_id"] == result["queue_id"]
        # Omitting a persisted optional parameter is a provenance change,
        # even when its saved value was null.
        missing_source = dict(params)
        missing_source.pop("source_quality_control_run_id")
        with pytest.raises(ValidationError, match="retry parameters changed"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=missing_source,
                inputs={"project": [source]},
            )
        with pytest.raises(ValidationError, match="retry parameters changed"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters={**params, "review_below_confidence": 0.5},
                inputs={"project": [source]},
            )
        with pytest.raises(ValidationError, match="foreign project"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id="not-the-project",
                parameters=params,
                inputs={"project": [source]},
            )

    listing = client.get(f"/api/v1/projects/{project['id']}/review-queues")
    assert listing.status_code == 200, listing.text
    assert len(listing.json()) == 2


def test_saved_qc_workflow_rejects_changed_priority_order(client: TestClient) -> None:
    """A saved workflow must reject swapped ranks without altering review decisions."""
    project = create_project(client, "QC saved ordering integrity")
    imported_ids: list[str] = []
    for name, size in (("priority-a.png", (80, 60)), ("priority-b.png", (81, 60))):
        imported = import_one(
            client,
            project["id"],
            filename=name,
            relative_path=f"qc-priority/{name}",
            size=size,
        )
        assert len(imported["successful"]) == 1
        imported_ids.append(imported["successful"][0]["image_id"])
    # Identical image bytes are deduplicated even with different filenames.
    assert len(set(imported_ids)) == 2

    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": _graph()},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run = queued.json()
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    record = detail.json()
    qc_node = next(n for n in record["nodes"] if n["node_id"] == "qc")
    artifact = next(a for a in record["artifacts"] if a["data_type"] == "review_queue_reference")
    queue_id = artifact["payload_json"]["queue_id"]
    assert artifact["payload_json"]["review_status"] == "requires_researcher_review"

    with app.state.session_factory() as session:
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run["id"],
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        node = session.get(WorkflowNodeRun, qc_node["id"])
        assert source is not None and node is not None
        params = {
            **dict(node.parameters_json or {}),
            "__workflow_run_id": run["id"],
            "__workflow_node_run_id": qc_node["id"],
        }
        rows = list(
            session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.review_queue_id == queue_id)
                .order_by(ReviewQueueItem.rank_position)
            )
        )
        assert len(rows) == 2
        rows[0].review_state = "in_progress"
        original_ranks = [item.rank_position for item in rows]
        rows[0].rank_position, rows[1].rank_position = 2, 1
        session.flush()
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            execute_runtime_adapter(
                "qc_review_queue",
                session=session,
                settings=app.state.settings,
                project_id=project["id"],
                parameters=params,
                inputs={"project": [source]},
            )
        assert rows[0].review_state == "in_progress"
        # Restore and prove ordinary retries still reuse the same queue.
        rows[0].rank_position, rows[1].rank_position = original_ranks
        session.flush()
        retried = execute_runtime_adapter(
            "qc_review_queue",
            session=session,
            settings=app.state.settings,
            project_id=project["id"],
            parameters=params,
            inputs={"project": [source]},
        )
        assert retried[0]["payload"]["queue_id"] == queue_id
