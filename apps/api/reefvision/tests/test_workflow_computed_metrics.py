import csv
import io
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ComputedMetricResult, WorkflowNodeRun
from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.computed_metrics import ComputedMetricService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_metrics import (
    add_records,
    create_density_definition,
    scientific_record,
)


def metric_graph(definition_id: str, organisms_id: str, area_id: str) -> dict[str, object]:
    return {
        "graph_id": "computed-density",
        "name": "Computed organism density",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "records",
                "node_type": "scientific_records_source",
                "parameters": {"record_ids": [organisms_id, area_id]},
            },
            {
                "node_id": "metric",
                "node_type": "computed_metric",
                "parameters": {
                    "definition_id": definition_id,
                    "bindings": {"organisms": organisms_id, "surveyed_area": area_id},
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-records",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "records",
                "target_port_id": "project",
            },
            {
                "edge_id": "records-metric",
                "source_node_id": "records",
                "source_port_id": "records",
                "target_node_id": "metric",
                "target_port_id": "records",
            },
        ],
    }


def save_and_queue(client: TestClient, project_id: str, graph: dict[str, object]) -> dict:
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    return queued.json()


@pytest.mark.parametrize("area_uncertainty", [None, 0.0, 1000.0])
def test_saved_workflow_executes_and_reloads_persisted_metric_result(
    client: TestClient, area_uncertainty: float | None
) -> None:
    project = create_project(client, "Metric workflow")
    organisms, area = add_records(
        client,
        project["id"],
        [
            scientific_record(
                "organism_count",
                12,
                "count",
                uncertainty={"value": 2, "kind": "standard_deviation"},
            ),
            scientific_record(
                "surveyed_area",
                20000,
                "cm2",
                uncertainty=(
                    {"value": area_uncertainty, "kind": "standard_deviation"}
                    if area_uncertainty is not None
                    else None
                ),
            ),
        ],
    )
    definition = create_density_definition(client, project["id"])
    graph = metric_graph(definition["id"], organisms["id"], area["id"])

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    registry_by_type = {item["node_type"]: item for item in registry.json()}
    assert registry_by_type["scientific_records_source"]["executable"] is True
    assert registry_by_type["computed_metric"]["input_ports"][0]["accepted_types"] == [
        "scientific_record_collection"
    ]
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    run = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["run"]["status"] == "succeeded"
    artifact = next(
        item for item in payload["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    assert artifact["payload_json"]["value"] == pytest.approx(6)
    assert artifact["payload_json"]["unit"] == "count/m2"
    assert len(artifact["payload_sha256"]) == 64
    results = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").json()
    assert results["total"] == 1
    assert results["items"][0]["id"] == artifact["payload_json"]["result_id"]
    assert results["items"][0]["workflow_run_id"] == run["id"]
    metric_node = next(node for node in payload["nodes"] if node["node_type"] == "computed_metric")
    assert results["items"][0]["workflow_node_run_id"] == metric_node["id"]
    result = results["items"][0]
    assert result["input_snapshot"]["surveyed_area"]["unit"] == "cm2"
    expected = None
    if area_uncertainty is not None:
        expected = (1 + (3 * area_uncertainty / 10000) ** 2) ** 0.5
    if expected is None:
        assert result["uncertainty"] is None
        assert result["normalized_uncertainty"] is None
        assert result["provenance"]["uncertainty_kind"] is None
        assert result["provenance"]["uncertainty_method"] == "unavailable_missing_input_uncertainty"
    else:
        assert result["uncertainty"] == pytest.approx(expected)
        assert result["normalized_uncertainty"] == pytest.approx(expected)
        assert result["provenance"]["uncertainty_kind"] == "standard_deviation"
        assert (
            result["provenance"]["uncertainty_method"] == "independent_first_order_root_sum_square"
        )
    exported = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results.csv")
    csv_row = next(csv.DictReader(io.StringIO(exported.text)))
    assert csv_row["workflow_run_id"] == run["id"]
    assert csv_row["workflow_node_run_id"] == metric_node["id"]
    if expected is None:
        assert csv_row["uncertainty"] == ""
        assert csv_row["normalized_uncertainty"] == ""
    else:
        assert float(csv_row["uncertainty"]) == pytest.approx(expected)
        assert float(csv_row["normalized_uncertainty"]) == pytest.approx(expected)

    with app.state.session_factory() as session:
        replay = ComputedMetricService(session).calculate(
            project["id"],
            definition["id"],
            {"organisms": organisms["id"], "surveyed_area": area["id"]},
            workflow_run_id=run["id"],
            workflow_node_run_id=metric_node["id"],
        )
        assert replay.id == results["items"][0]["id"]
        for wrong_run_id in (str(uuid4()), None):
            with pytest.raises(ConflictError, match="conflicts"):
                ComputedMetricService(session).calculate(
                    project["id"],
                    definition["id"],
                    {"organisms": organisms["id"], "surveyed_area": area["id"]},
                    workflow_run_id=wrong_run_id,
                    workflow_node_run_id=metric_node["id"],
                )
        repeated = ComputedMetricService(session).calculate(
            project["id"],
            definition["id"],
            {"organisms": organisms["id"], "surveyed_area": area["id"]},
            workflow_run_id=run["id"],
            workflow_node_run_id=metric_node["id"],
        )
        assert repeated.id == replay.id
        assert repeated.content_sha256 == replay.content_sha256
        assert repeated.workflow_run_id == run["id"]
        with pytest.raises(ConflictError, match="conflicts"):
            ComputedMetricService(session).calculate(
                project["id"],
                definition["id"],
                {"organisms": area["id"], "surveyed_area": organisms["id"]},
                workflow_run_id=run["id"],
                workflow_node_run_id=metric_node["id"],
            )


@pytest.mark.parametrize(
    "failure",
    [
        "missing_record",
        "outside_source",
        "duplicate_binding",
        "qc_rejected",
        "qc_suspect",
        "area_qc_rejected",
        "area_qc_suspect",
        "mixed_uncertainty_kind",
        "bounded_uncertainty",
        "zero_area",
        "mismatched_observation_time",
        "mismatched_location",
        "mismatched_depth",
        "mismatched_dataset",
        "mismatched_station",
        "mismatched_depth_reference",
        "unknown_shared_location",
        "unknown_shared_depth",
        "unknown_shared_dataset",
    ],
)
def test_workflow_metric_failure_is_persisted_without_result(
    client: TestClient, failure: str
) -> None:
    project = create_project(client, f"Metric workflow {failure}")
    qc_by_failure = {"qc_rejected": "rejected", "qc_suspect": "suspect"}
    context_overrides: dict[str, object] = {}
    shared_overrides: dict[str, object] = {}
    if failure == "unknown_shared_location":
        shared_overrides["location"] = None
    elif failure == "unknown_shared_depth":
        shared_overrides.update(depth_m=None, depth_reference=None)
    elif failure == "unknown_shared_dataset":
        shared_overrides["provenance"] = {
            "source": "Reef survey",
            "acquired_at": "2026-04-03T13:05:00Z",
        }
    if failure == "mismatched_location":
        context_overrides["location"] = {"latitude": 25.1, "longitude": -80}
    elif failure == "mismatched_depth":
        context_overrides["depth_m"] = 11
    elif failure == "mismatched_dataset":
        context_overrides["provenance"] = {
            "source": "Reef survey",
            "dataset_id": "different-survey",
            "acquired_at": "2026-04-03T13:05:00Z",
        }
    elif failure == "mismatched_station":
        context_overrides["provenance"] = {
            "source": "Reef survey",
            "dataset_id": "survey-2026",
            "acquired_at": "2026-04-03T13:05:00Z",
            "source_metadata": {"station_id": "station-b"},
        }
    elif failure == "mismatched_depth_reference":
        context_overrides["depth_reference"] = "chart_datum"
    organisms, area = add_records(
        client,
        project["id"],
        [
            scientific_record(
                "organism_count",
                12,
                "count",
                qc=qc_by_failure.get(failure, "unassessed"),
                uncertainty={"value": 2, "kind": "standard_deviation"},
                **shared_overrides,
            ),
            scientific_record(
                "surveyed_area",
                0 if failure == "zero_area" else 2,
                "m2",
                observed_at=(
                    "2026-04-03T13:01:00Z"
                    if failure == "mismatched_observation_time"
                    else "2026-04-03T13:00:00Z"
                ),
                qc={"area_qc_rejected": "rejected", "area_qc_suspect": "suspect"}.get(
                    failure, "unassessed"
                ),
                uncertainty={
                    "value": 0.1,
                    "kind": {
                        "mixed_uncertainty_kind": "standard_error",
                        "bounded_uncertainty": "bound",
                    }.get(failure, "standard_deviation"),
                },
                **{**shared_overrides, **context_overrides},
            ),
        ],
    )
    definition = create_density_definition(client, project["id"])
    graph = metric_graph(definition["id"], organisms["id"], area["id"])
    nodes = cast(list[dict], graph["nodes"])
    if failure == "missing_record":
        nodes[1]["parameters"] = {"record_ids": [str(uuid4()), area["id"]]}
    elif failure == "outside_source":
        nodes[1]["parameters"] = {"record_ids": [organisms["id"]]}
    elif failure == "duplicate_binding":
        nodes[2]["parameters"]["bindings"] = {
            "organisms": organisms["id"],
            "surveyed_area": organisms["id"],
        }

    run = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    assert detail["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "computed_metric_result" for artifact in detail["artifacts"]
    )
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").json()["total"] == 0
    )
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(ComputedMetricResult).where(ComputedMetricResult.project_id == project["id"])
            )
            is None
        )
        failed_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run["id"],
                WorkflowNodeRun.status == "failed",
            )
        )
        assert failed_node is not None
        if failure == "duplicate_binding":
            assert "distinct scientific record" in (failed_node.error_message or "")
        if failure in {"qc_rejected", "qc_suspect", "area_qc_rejected", "area_qc_suspect"}:
            assert "suspect or rejected" in (failed_node.error_message or "")
        if failure in {"mixed_uncertainty_kind", "bounded_uncertainty"}:
            assert "Unsupported uncertainty kind combination" in (failed_node.error_message or "")
        if failure == "zero_area":
            assert "Division by zero" in (failed_node.error_message or "")
        if failure == "mismatched_observation_time":
            assert "exact observation time" in (failed_node.error_message or "")
        if failure in {
            "mismatched_location",
            "mismatched_depth",
            "mismatched_dataset",
            "mismatched_station",
            "mismatched_depth_reference",
            "unknown_shared_location",
            "unknown_shared_depth",
            "unknown_shared_dataset",
        }:
            assert "explicit shared contextual identity" in (failed_node.error_message or "")
