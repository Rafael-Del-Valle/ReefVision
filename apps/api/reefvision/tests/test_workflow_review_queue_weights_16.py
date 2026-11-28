"""QC scoring weights agree between standalone and executable saved workflows."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from reefvision.db.models import (
    PredictionProposal,
    ReviewQueue,
    ReviewQueueItem,
    WorkflowArtifact,
    WorkflowNodeRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.review_queues import ReviewScoreWeights
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.services.workflow_review_queue_integrity import (
    queue_item_evidence_sha256,
    validate_saved_queue_snapshot,
)
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_review_queue_prediction_confidence_integrity_16 import _local_prediction
from reefvision.tests.test_workflow_review_queue_16 import _graph


def _weighted_graph(weights: dict[str, float] | None) -> dict[str, Any]:
    graph = _graph()
    graph["nodes"] = [
        {"node_id": "project", "node_type": "project_source"},
        {
            "node_id": "qc",
            "node_type": "qc_review_queue",
            "parameters": {"signal_weights": weights},
        },
    ]
    return graph


def _execute(client: TestClient, project_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    return detail.json()


def _payload(detail: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item["payload_json"]
        for item in detail["artifacts"]
        if item["data_type"] == "review_queue_reference"
    ]
    assert len(matches) == 1
    return matches[0]


def test_saved_custom_weights_match_standalone_scoring(client: TestClient) -> None:
    project = create_project(client, "Researcher-weighted coral QC")
    project_id = project["id"]
    assert len(import_one(client, project_id, filename="weighted-coral.png")["successful"]) == 1
    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights["unreviewed_state"] = 1.0
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues", json={"signal_weights": weights}
    )
    assert standalone.status_code == 201, standalone.text
    graph = _weighted_graph(weights)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    payload = _payload(_execute(client, project_id, graph))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    workflow = client.get(f"/api/v1/review-queues/{payload['queue_id']}")
    assert workflow.status_code == 200, workflow.text
    assert workflow.json()["configuration_json"]["weights"] == weights
    standalone_items = client.get(f"/api/v1/review-queues/{standalone.json()['id']}/items").json()[
        "items"
    ]
    workflow_items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items").json()[
        "items"
    ]
    assert len(standalone_items) == len(workflow_items) == 1
    assert standalone_items[0]["score"] == workflow_items[0]["score"]
    assert standalone_items[0]["input_checksum"] == workflow_items[0]["input_checksum"]
    assert workflow_items[0]["review_state"] == "pending"


@pytest.mark.parametrize(
    "weights",
    [
        {name: 0.0 for name in ReviewScoreWeights.model_fields},
        {"not_a_qc_signal": 1.0},
        {"recent_import": 2.0, "recent_improt": 3.0},
        {"unreviewed_state": -1.0},
        {"low_mean_confidence": 1e308, "low_min_confidence": 1e308},
    ],
)
def test_invalid_weights_fail_saved_graph_planning(
    client: TestClient, weights: dict[str, float]
) -> None:
    project_id = create_project(client, "Invalid workflow QC weights")["id"]
    imported = import_one(client, project_id, filename="invalid-weights-coral.png")
    assert len(imported["successful"]) == 1
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues", json={"signal_weights": weights}
    )
    assert standalone.status_code == 422, standalone.text
    plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan",
        json=_weighted_graph(weights),
    )
    assert plan.status_code == 200, plan.text
    assert not plan.json()["valid"] and not plan.json()["executable"]
    assert any(issue["code"] == "invalid_qc_signal_weights" for issue in plan.json()["issues"])
    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert queues.json() == []


@pytest.mark.parametrize("threshold", [True, False, "0.75", -0.01, 1.01, [], {}])
def test_invalid_confidence_threshold_refused_before_qc_execution(
    client: TestClient, threshold: Any
) -> None:
    project_id, _ = _local_prediction(client)
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"review_below_confidence": threshold},
    )
    assert standalone.status_code == 422, standalone.text
    graph = _weighted_graph(None)
    graph["nodes"][1]["parameters"]["review_below_confidence"] = threshold
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert not plan.json()["valid"] and not plan.json()["executable"]
    assert any(
        issue["code"] == "invalid_qc_confidence_threshold" for issue in plan.json()["issues"]
    )
    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert queues.json() == []


@pytest.mark.parametrize("threshold", [0, 1])
def test_numeric_confidence_boundary_matches_saved_qc(client: TestClient, threshold: int) -> None:
    project_id, prediction_id = _local_prediction(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        prediction = session.get(PredictionProposal, prediction_id)
        assert prediction is not None
        prediction.confidence = float(threshold)
        session.commit()
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"review_below_confidence": threshold},
    )
    assert standalone.status_code == 201, standalone.text
    graph = _weighted_graph(None)
    graph["nodes"][1]["parameters"]["review_below_confidence"] = threshold
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    payload = _payload(_execute(client, project_id, graph))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    for queue_id in (standalone.json()["id"], payload["queue_id"]):
        queue = client.get(f"/api/v1/review-queues/{queue_id}")
        assert queue.status_code == 200, queue.text
        assert queue.json()["configuration_json"]["review_below_confidence"] == threshold
        items = client.get(f"/api/v1/review-queues/{queue_id}/items")
        assert items.status_code == 200, items.text
        assert len(items.json()["items"]) == 1
        assert items.json()["items"][0]["review_state"] == "pending"


@pytest.mark.parametrize("number", [0, 1])
@pytest.mark.parametrize("saved_invalid", [True, False])
@pytest.mark.parametrize("field", ["review_below_confidence", "signal_weights"])
def test_qc_retry_rejects_equal_looking_boolean_parameters(
    client: TestClient, number: int, saved_invalid: bool, field: str
) -> None:
    project_id, prediction_id = _local_prediction(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        prediction = session.get(PredictionProposal, prediction_id)
        assert prediction is not None
        prediction.confidence = float(number)
        session.commit()
    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights["unreviewed_state"] = 1.0
    graph = _weighted_graph(weights)
    graph["nodes"][1]["parameters"]["review_below_confidence"] = number
    payload = _payload(_execute(client, project_id, graph))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"

    with app.state.session_factory() as session:
        nodes = session.scalars(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"]
            )
        ).all()
        node = next(row for row in nodes if row.node_type == "qc_review_queue")
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        assert source is not None
        original = dict(node.parameters_json)
        if field == "signal_weights":
            signal = "unreviewed_state" if number else "recent_import"
            malformed = {
                **original,
                field: {**original[field], signal: bool(number)},
            }
        else:
            malformed = {**original, field: bool(number)}
        # This is the original guard's blind spot, not a changed numeric value.
        assert malformed == original
        if saved_invalid:
            # Bypass ORM equality-based dirty detection: the malformed JSON
            # must actually be present in SQLite inside this transaction.
            session.execute(
                update(WorkflowNodeRun)
                .where(WorkflowNodeRun.id == node.id)
                .values(parameters_json=malformed)
                .execution_options(synchronize_session=False)
            )
            session.expire(node, ["parameters_json"])
            persisted = node.parameters_json[field]
            if field == "signal_weights":
                assert type(persisted[signal]) is bool
            else:
                assert type(persisted) is bool
        runtime = {
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        supplied = original if saved_invalid else malformed
        with pytest.raises(ValidationError, match=r"invalid (signal_weights|review parameters)"):
            create_review_queue_workflow_artifact(
                session,
                app.state.settings,
                project_id,
                {**supplied, **runtime},
                {"project": [source]},
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, {**original, **runtime}, {"project": [source]}
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert [queue["id"] for queue in queues.json()] == [payload["queue_id"]]
    items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items")
    assert items.status_code == 200, items.text
    assert len(items.json()["items"]) == 1
    assert items.json()["items"][0]["review_state"] == "pending"


@pytest.mark.parametrize("shape", ["pairs", "duplicate_pairs", "empty_array", "null", "false"])
def test_saved_qc_retry_rejects_nonobject_parameter_contract(
    client: TestClient, shape: str
) -> None:
    project_id = create_project(client, "Malformed QC parameter contract")["id"]
    assert len(import_one(client, project_id, filename="parameter-coral.png")["successful"]) == 1
    payload = _payload(_execute(client, project_id, _weighted_graph(None)))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"],
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        assert node is not None and source is not None
        original = dict(node.parameters_json)
        pairs = [[key, value] for key, value in original.items()]
        malformed: Any = {
            "pairs": pairs,
            "duplicate_pairs": [["signal_weights", True], *pairs],
            "empty_array": [],
            "null": None,
            "false": False,
        }[shape]
        if shape in {"pairs", "duplicate_pairs"}:
            assert dict(malformed) == original
        session.execute(
            update(WorkflowNodeRun)
            .where(WorkflowNodeRun.id == node.id)
            .values(parameters_json=malformed)
            .execution_options(synchronize_session=False)
        )
        session.expire(node, ["parameters_json"])
        assert type(node.parameters_json) is type(malformed)
        parameters = {
            **original,
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        with pytest.raises(ValidationError, match="invalid saved parameter object"):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, {"project": [source]}
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, {"project": [source]}
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert [queue["id"] for queue in queues.json()] == [payload["queue_id"]]
    items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items")
    assert items.status_code == 200, items.text
    assert len(items.json()["items"]) == 1
    assert items.json()["items"][0]["review_state"] == "pending"


@pytest.mark.parametrize("legacy", [True, False])
def test_saved_qc_retry_preserves_original_weights_and_legacy_defaults(
    client: TestClient, legacy: bool
) -> None:
    project_id = create_project(client, "QC weight retry integrity")["id"]
    assert len(import_one(client, project_id, filename="retry-weight.png")["successful"]) == 1
    weights = None
    if not legacy:
        weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
        weights["unreviewed_state"] = 1.0
    payload = _payload(_execute(client, project_id, _weighted_graph(weights)))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        nodes = session.scalars(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"]
            )
        ).all()
        node = next(item for item in nodes if item.node_type == "qc_review_queue")
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        assert source is not None
        if legacy:
            node.parameters_json = {
                key: value for key, value in node.parameters_json.items() if key != "signal_weights"
            }
        else:
            node.parameters_json = {**node.parameters_json, "signal_weights": None}
        session.flush()
        parameters = {
            **node.parameters_json,
            "signal_weights": None,
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        if legacy:
            output = create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, {"project": [source]}
            )
            assert output[0]["payload"] == payload
        else:
            with pytest.raises(ValidationError, match="parameters changed or queue incomplete"):
                create_review_queue_workflow_artifact(
                    session, app.state.settings, project_id, parameters, {"project": [source]}
                )
        session.rollback()
    items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items")
    assert items.status_code == 200, items.text
    assert items.json()["items"][0]["review_state"] == "pending"


@pytest.mark.parametrize(
    ("prediction_status", "minimum", "threshold"),
    [
        ("pending", 0.1, None),
        ("pending", 0.5, None),
        ("rejected", 0.1, None),
        ("rejected", 0.5, None),
        ("two_pending", 0.6, None),
        ("two_pending", 0.9, None),
        ("two_pending", 0.4, 0.75),
        ("two_pending", 0.5, 0.75),
    ],
)
def test_prediction_confidence_evidence_on_saved_qc_retry(
    client: TestClient, prediction_status: str, minimum: float, threshold: float | None
) -> None:
    project_id, prediction_id = _local_prediction(
        client, additional_pending=prediction_status == "two_pending"
    )
    app = cast(FastAPI, client.app)
    if prediction_status == "rejected":
        with app.state.session_factory() as session:
            proposal = session.get(PredictionProposal, prediction_id)
            assert proposal is not None
            proposal.review_status = "rejected"
            session.commit()
    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights["unreviewed_state"] = 1.0
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"signal_weights": weights, "review_below_confidence": threshold},
    )
    assert standalone.status_code == 201, standalone.text
    graph = _weighted_graph(weights)
    if threshold is not None:
        graph["nodes"][1]["parameters"]["review_below_confidence"] = threshold
    payload = _payload(_execute(client, project_id, graph))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"

    with app.state.session_factory() as session:
        for queue_id in (standalone.json()["id"], payload["queue_id"]):
            queue = session.get(ReviewQueue, queue_id)
            assert queue is not None
            items = session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == queue_id)
            ).all()
            assert len(items) == 1
            item = items[0]
            expected_counts = {"pending": 1.0, "rejected": 0.0, "two_pending": 2.0}
            expected_count = expected_counts[prediction_status]
            expected_signal = 0.25 if expected_count else 0.0
            assert item.signal_values_json["pending_proposals"] == expected_count
            assert item.signal_values_json["low_mean_confidence"] == expected_signal
            assert item.signal_values_json["low_min_confidence"] == expected_signal
            assert item.model_ids_json
            validate_saved_queue_snapshot(queue, items)

            # The minimum has zero weight. Change its evidence and re-sign
            # the digest without changing the priority, summary or review.
            item.signal_values_json = {**item.signal_values_json, "low_min_confidence": minimum}
            item.normalized_signals_json = {
                **item.normalized_signals_json,
                "low_min_confidence": minimum,
            }
            item.score_breakdown_json = [
                {**part, "raw_value": minimum, "normalized_value": minimum}
                if part["signal_id"] == "low_min_confidence"
                else part
                for part in item.score_breakdown_json
            ]
            queue.input_checksums_json = {
                **queue.input_checksums_json,
                "item_evidence_sha256": queue_item_evidence_sha256(items),
            }
            session.flush()
            with pytest.raises(ValidationError, match="snapshot failed integrity"):
                validate_saved_queue_snapshot(queue, items)
            assert item.review_state == "pending"
            if queue_id == payload["queue_id"]:
                nodes = session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"]
                    )
                ).all()
                node = next(row for row in nodes if row.node_type == "qc_review_queue")
                source = session.scalar(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                        WorkflowArtifact.producer_port_id == "project",
                    )
                )
                assert source is not None
                parameters = {
                    **node.parameters_json,
                    "__workflow_run_id": payload["workflow_run_id"],
                    "__workflow_node_run_id": node.id,
                }
                with pytest.raises(ValidationError, match="snapshot failed integrity"):
                    create_review_queue_workflow_artifact(
                        session, app.state.settings, project_id, parameters, {"project": [source]}
                    )
                session.rollback()
                replay = create_review_queue_workflow_artifact(
                    session, app.state.settings, project_id, parameters, {"project": [source]}
                )
                assert replay[0]["payload"] == payload
            session.rollback()


@pytest.mark.parametrize(
    ("signal_id", "value"),
    [
        ("edited_acceptance_rate", 0.5),
        ("edited_acceptance_rate", 1.0),
        ("count_disagreement", 0.25),
        ("count_disagreement", 0.5),
    ],
)
def test_fully_rejected_prediction_evidence_on_saved_qc_retry(
    client: TestClient, signal_id: str, value: float
) -> None:
    project_id, prediction_id = _local_prediction(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, prediction_id)
        assert proposal is not None
        proposal.review_status = "rejected"
        session.commit()
    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights["unreviewed_state"] = 1.0
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"signal_weights": weights},
    )
    assert standalone.status_code == 201, standalone.text
    graph = _weighted_graph(weights)
    payload = _payload(_execute(client, project_id, graph))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"

    with app.state.session_factory() as session:
        for queue_id in (standalone.json()["id"], payload["queue_id"]):
            queue = session.get(ReviewQueue, queue_id)
            assert queue is not None
            items = session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == queue_id)
            ).all()
            assert len(items) == 1
            item = items[0]
            assert item.signal_values_json["rejection_rate"] == 1.0
            assert item.signal_values_json["pending_proposals"] == 0.0
            assert item.signal_values_json["edited_acceptance_rate"] == 0.0
            assert item.signal_values_json["count_disagreement"] == 0.0
            assert item.model_ids_json
            validate_saved_queue_snapshot(queue, items)

            # Re-sign impossible evidence without changing the score.
            assert item.weights_json[signal_id] == 0.0
            item.signal_values_json = {**item.signal_values_json, signal_id: value}
            item.normalized_signals_json = {
                **item.normalized_signals_json,
                signal_id: value,
            }
            item.score_breakdown_json = [
                {**part, "raw_value": value, "normalized_value": value}
                if part["signal_id"] == signal_id
                else part
                for part in item.score_breakdown_json
            ]
            queue.input_checksums_json = {
                **queue.input_checksums_json,
                "item_evidence_sha256": queue_item_evidence_sha256(items),
            }
            session.flush()
            with pytest.raises(ValidationError, match="snapshot failed integrity"):
                validate_saved_queue_snapshot(queue, items)
            assert item.review_state == "pending"
            if queue_id == payload["queue_id"]:
                nodes = session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"]
                    )
                ).all()
                node = next(row for row in nodes if row.node_type == "qc_review_queue")
                source = session.scalar(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                        WorkflowArtifact.producer_port_id == "project",
                    )
                )
                assert source is not None
                parameters = {
                    **node.parameters_json,
                    "__workflow_run_id": payload["workflow_run_id"],
                    "__workflow_node_run_id": node.id,
                }
                with pytest.raises(ValidationError, match="snapshot failed integrity"):
                    create_review_queue_workflow_artifact(
                        session, app.state.settings, project_id, parameters, {"project": [source]}
                    )
                session.rollback()
                replay = create_review_queue_workflow_artifact(
                    session, app.state.settings, project_id, parameters, {"project": [source]}
                )
                assert replay[0]["payload"] == payload
            session.rollback()


@pytest.mark.parametrize("shape", ["null", "false", "zero", "string", "object"])
def test_interrupted_qc_retry_requires_real_output_list(client: TestClient, shape: str) -> None:
    project_id = create_project(client, "Interrupted QC output contract")["id"]
    assert len(import_one(client, project_id, filename="output-coral.png")["successful"]) == 1
    payload = _payload(_execute(client, project_id, _weighted_graph(None)))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"],
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        assert node is not None and source is not None
        parameters = {
            **node.parameters_json,
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        malformed: Any = {"null": None, "false": False, "zero": 0, "string": "", "object": {}}[
            shape
        ]
        session.execute(
            update(WorkflowNodeRun)
            .where(WorkflowNodeRun.id == node.id)
            .values(status="running", output_artifact_ids_json=malformed)
            .execution_options(synchronize_session=False)
        )
        session.expire(node, ["status", "output_artifact_ids_json"])
        assert node.status == "running"
        assert type(node.output_artifact_ids_json) is type(malformed)
        with pytest.raises(ValidationError, match="saved output binding is invalid"):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, {"project": [source]}
            )
        # A real empty list remains a supported interrupted-output retry.
        session.execute(
            update(WorkflowNodeRun)
            .where(WorkflowNodeRun.id == node.id)
            .values(output_artifact_ids_json=[])
            .execution_options(synchronize_session=False)
        )
        session.expire(node, ["output_artifact_ids_json"])
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, {"project": [source]}
        )
        assert replay[0]["payload"] == payload
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, {"project": [source]}
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert [queue["id"] for queue in queues.json()] == [payload["queue_id"]]
    items = client.get(f"/api/v1/review-queues/{payload['queue_id']}/items")
    assert items.status_code == 200, items.text
    assert items.json()["items"][0]["review_state"] == "pending"


@pytest.mark.parametrize("shape", ["scalar", "broken_pairs"])
def test_qc_retry_refuses_malformed_queue_configuration(client: TestClient, shape: str) -> None:
    project_id = create_project(client, "Malformed QC queue configuration")["id"]
    assert len(import_one(client, project_id, filename="config-coral.png")["successful"]) == 1
    payload = _payload(_execute(client, project_id, _weighted_graph(None)))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"],
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        queue = session.get(ReviewQueue, payload["queue_id"])
        assert node is not None and source is not None and queue is not None
        parameters = {
            **node.parameters_json,
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        malformed: Any = 7 if shape == "scalar" else [["weights"]]
        session.execute(
            update(ReviewQueue)
            .where(ReviewQueue.id == queue.id)
            .values(configuration_json=malformed)
            .execution_options(synchronize_session=False)
        )
        session.expire(queue, ["configuration_json"])
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            validate_saved_queue_snapshot(queue, queue.items)
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, {"project": [source]}
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, {"project": [source]}
        )
        assert replay[0]["payload"] == payload
        session.rollback()


def test_half_cent_score_survives_standalone_and_saved_qc_replay(client: TestClient) -> None:
    project_id, prediction_id = _local_prediction(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, prediction_id)
        assert proposal is not None
        proposal.confidence = 0.2
        session.commit()

    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights.update(
        low_mean_confidence=29.0,
        low_min_confidence=28.0,
        pending_proposals=16.0,
        unreviewed_state=23.0,
    )
    standalone = client.post(
        f"/api/v1/projects/{project_id}/review-queues", json={"signal_weights": weights}
    )
    assert standalone.status_code == 201, standalone.text
    payload = _payload(_execute(client, project_id, _weighted_graph(weights)))
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    with app.state.session_factory() as session:
        for queue_id in (standalone.json()["id"], payload["queue_id"]):
            queue = session.get(ReviewQueue, queue_id)
            assert queue is not None
            items = session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == queue_id)
            ).all()
            assert len(items) == 1
            item = items[0]
            assert item.score == 73.12
            assert item.review_state == "pending"
            validate_saved_queue_snapshot(queue, items)
            # Canonical JSON checksums do not depend on object insertion order.
            item.signal_values_json = dict(reversed(list(item.signal_values_json.items())))
            item.normalized_signals_json = dict(
                reversed(list(item.normalized_signals_json.items()))
            )
            validate_saved_queue_snapshot(queue, items)
            session.rollback()

        nodes = session.scalars(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == payload["workflow_run_id"]
            )
        ).all()
        node = next(row for row in nodes if row.node_type == "qc_review_queue")
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == payload["workflow_run_id"],
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        assert source is not None
        parameters = {
            **node.parameters_json,
            "__workflow_run_id": payload["workflow_run_id"],
            "__workflow_node_run_id": node.id,
        }
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, {"project": [source]}
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    regenerated = client.post(f"/api/v1/review-queues/{standalone.json()['id']}/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    items = client.get(f"/api/v1/review-queues/{regenerated.json()['id']}/items")
    assert items.status_code == 200, items.text
    assert items.json()["items"][0]["score"] == 73.12
    assert items.json()["items"][0]["review_state"] == "pending"
