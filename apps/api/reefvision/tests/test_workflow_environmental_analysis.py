"""Environmental analyses are executable Workflow Builder nodes with persisted lineage."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.environmental_analysis import ObservationEnvironmentJoinRequest
from reefvision.services.environmental_analysis import EnvironmentalAnalysisService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_environmental_analysis_temporal import _records
from reefvision.tests.test_environmental_analysis_tides import _import_tides
from reefvision.tests.test_scientific_data import observation
from reefvision.tests.test_workflow_computed_metrics import save_and_queue
from reefvision.tests.test_workflow_environmental_threshold import threshold_query

NODE_TYPES = {
    "current_streamline_analysis",
    "lunar_context_analysis",
    "tidal_context_analysis",
    "event_window_analysis",
    "observation_environment_join",
    "lagged_comparison",
}


def lunar_graph() -> dict:
    return {
        "graph_id": "persisted-lunar-context",
        "name": "Persisted lunar context",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "lunar",
                "node_type": "lunar_context_analysis",
                "parameters": {
                    "name": "Workflow lunar context",
                    "observed_at": ["2024-04-08T18:21:00Z"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-lunar",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "lunar",
                "target_port_id": "project",
            }
        ],
    }


def analysis_graph(node_type: str, parameters: dict) -> dict:
    return {
        "graph_id": f"workflow-{node_type}",
        "name": node_type.replace("_", " "),
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "analysis", "node_type": node_type, "parameters": parameters},
        ],
        "edges": [
            {
                "edge_id": "project-analysis",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "analysis",
                "target_port_id": "project",
            }
        ],
    }


def _execute(client: TestClient, project_id: str, graph: dict) -> tuple[dict, dict]:
    run = save_and_queue(client, project_id, graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "environmental_analysis_result"
    )
    return run, artifact


def test_environmental_analysis_nodes_are_typed_and_executable(client: TestClient) -> None:
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    definitions = {item["node_type"]: item for item in registry.json()}
    assert NODE_TYPES.issubset(definitions)
    for node_type in NODE_TYPES:
        definition = definitions[node_type]
        assert definition["executable"] is True
        assert definition["input_ports"][0]["accepted_types"] == ["project_reference"]
        assert definition["output_ports"][0]["accepted_types"] == ["environmental_analysis_result"]


def test_lunar_workflow_persists_lineage_and_saved_graph_replay_is_deterministic(
    client: TestClient,
) -> None:
    project = create_project(client, "Lunar workflow")
    graph = lunar_graph()
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    first_run, first_artifact = _execute(client, project["id"], graph)
    first = first_artifact["payload_json"]
    assert first["analysis_kind"] == "lunar_context"
    assert first["payload"]["phase"] == "new_moon"
    assert first["workflow_run_id"] == first_run["id"]
    assert first["workflow_node_run_id"]
    assert len(first["content_sha256"]) == 64
    assert len(first_artifact["payload_sha256"]) == 64

    second_run, second_artifact = _execute(client, project["id"], graph)
    second = second_artifact["payload_json"]
    assert second_run["workflow_graph_record_id"] == first_run["workflow_graph_record_id"]
    assert second["result_id"] != first["result_id"]
    assert second["payload"] == first["payload"]
    assert second["input_snapshot"] == first["input_snapshot"]
    assert second["definition_sha256"] == first["definition_sha256"]

    results = client.get(
        f"/api/v1/projects/{project['id']}/environment/analyses/results",
        params={"analysis_kind": "lunar_context"},
    )
    assert results.status_code == 200, results.text
    assert results.json()["total"] == 2


def test_saved_join_replays_explicit_sampling_effort(client: TestClient) -> None:
    project_id = create_project(client, "Workflow sampling effort")["id"]
    [record] = _records(
        client, project_id, [observation(variable="coral_count", value=4, unit="count")]
    )
    graph = analysis_graph(
        "observation_environment_join",
        {
            "name": "Unmatched workflow evidence",
            "observation_record_ids": [record["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 60,
            "max_distance_m": 1000,
            "require_depth_match": False,
            "unmatched_policy": "retain",
        },
    )
    first_run, first = _execute(client, project_id, graph)
    second_run, second = _execute(client, project_id, graph)
    assert first_run["workflow_graph_record_id"] == second_run["workflow_graph_record_id"]
    first_payload = first["payload_json"]["payload"]
    assert second["payload_json"]["payload"] == first_payload
    assert first_payload["sampling_effort"] == {"requested": 1, "matched": 0, "unmatched": 1}
    assert first_payload["experimental_unit_basis"] == "undeclared"
    assert first_payload["unmatched"][0]["observation_record_id"] == record["id"]
    assert "independent_unit_id" not in first_payload["unmatched"][0]
    app = cast(FastAPI, client.app)
    saved = first["payload_json"]
    request = ObservationEnvironmentJoinRequest.model_validate(saved["input_snapshot"])
    context = {
        "workflow_run_id": saved["workflow_run_id"],
        "workflow_node_run_id": saved["workflow_node_run_id"],
    }
    with app.state.session_factory() as session:
        service = EnvironmentalAnalysisService(session)
        existing = service.create_observation_environment_join(project_id, request, **context)
        assert str(existing.result.id) == saved["result_id"]
        with pytest.raises(ConflictError, match="conflicts with its saved inputs"):
            service.create_observation_environment_join(
                project_id, request.model_copy(update={"max_distance_m": 10}), **context
            )


def test_tidal_window_join_and_lag_workflow_nodes_execute_end_to_end(
    client: TestClient,
) -> None:
    project = create_project(client, "Environmental analysis workflows")
    _import_tides(client, project["id"])
    records = _records(
        client,
        project["id"],
        [
            observation(
                variable="coral_count",
                value=4,
                unit="count",
                observed_at="2026-04-03T13:00:00Z",
            ),
            observation(value=72, unit="degF", observed_at="2026-04-03T13:00:00Z"),
            observation(value=68, unit="degF", observed_at="2026-04-03T13:05:00Z"),
        ],
    )
    query = threshold_query()
    query.update({"max_time_delta_s": 600, "threshold_value": 20, "threshold_unit": "degC"})
    event = client.post(
        f"/api/v1/projects/{project['id']}/environment/events/definitions",
        json={"name": "Warm workflow samples", "query": query},
    )
    assert event.status_code == 201, event.text
    direct_join = client.post(
        f"/api/v1/projects/{project['id']}/environment/analyses/observation-environment-join",
        json={
            "name": "Lag source",
            "observation_record_ids": [records[0]["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 600,
            "max_distance_m": 1000,
            "require_depth_match": False,
        },
    )
    assert direct_join.status_code == 201, direct_join.text
    cases = [
        (
            "tidal_context_analysis",
            "tidal_context",
            {
                "name": "Workflow tide",
                "observed_at": "2026-04-03T13:00:00Z",
                "location": {"latitude": 32.7808, "longitude": -79.9236},
                "station_id": "8665530",
                "datum": "MLLW",
                "max_time_delta_s": 900,
                "max_distance_m": 1000,
            },
        ),
        (
            "event_window_analysis",
            "event_window",
            {
                "name": "Workflow event windows",
                "event_definition_id": event.json()["id"],
                "before_s": 60,
                "after_s": 60,
                "boundary_policy": "inclusive",
            },
        ),
        (
            "observation_environment_join",
            "observation_environment_join",
            {
                "name": "Workflow join",
                "observation_record_ids": [records[0]["id"]],
                "environmental_variable": "water_temperature",
                "max_time_delta_s": 600,
                "max_distance_m": 1000,
                "require_depth_match": False,
            },
        ),
        (
            "lagged_comparison",
            "lagged_comparison",
            {
                "name": "Workflow lag",
                "join_result_id": direct_join.json()["result"]["id"],
                "lags_s": [0, 300],
            },
        ),
    ]
    for node_type, expected_kind, parameters in cases:
        run, artifact = _execute(client, project["id"], analysis_graph(node_type, parameters))
        payload = artifact["payload_json"]
        assert payload["analysis_kind"] == expected_kind
        assert payload["workflow_run_id"] == run["id"]
        assert payload["workflow_node_run_id"]
