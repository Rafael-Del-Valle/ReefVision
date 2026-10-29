"""Saved environmental threshold workflows preserve scientific evidence and failure state."""

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_data import observation
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def threshold_graph(query: dict) -> dict:
    return {
        "graph_id": "environmental-threshold",
        "name": "Observed temperature threshold",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "threshold",
                "node_type": "environmental_threshold",
                "parameters": {"query": query},
            },
        ],
        "edges": [
            {
                "edge_id": "project-threshold",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "threshold",
                "target_port_id": "project",
            }
        ],
    }


def threshold_query() -> dict:
    return {
        "variable": "water_temperature",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "observed_at": "2026-04-03T13:00:00Z",
        "max_distance_m": 1000,
        "max_time_delta_s": 60,
        "source_kinds": ["observed"],
        "threshold_value": 68,
        "threshold_unit": "degF",
        "direction": "above",
    }


def test_saved_environmental_threshold_workflow_persists_provenance(client: TestClient) -> None:
    project = create_project(client, "Environmental workflow")
    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    saved = client.post(
        records_url,
        json={
            "records": [
                observation(value=22, unit="degC", qc="accepted"),
                observation(value=18, unit="degC", qc="accepted"),
                observation(value=25, unit="degC", qc="suspect"),
            ]
        },
    )
    assert saved.status_code == 201, saved.text
    record_ids = [item["id"] for item in saved.json()["items"]]
    graph = threshold_graph(threshold_query())

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    definitions = {item["node_type"]: item for item in registry.json()}
    assert definitions["environmental_threshold"]["executable"] is True
    assert definitions["environmental_threshold"]["output_ports"][0]["accepted_types"] == [
        "environmental_threshold_samples"
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
    result = next(
        artifact
        for artifact in payload["artifacts"]
        if artifact["data_type"] == "environmental_threshold_samples"
    )
    snapshot = result["payload_json"]
    assert snapshot["method"] == "observed_sample_threshold_no_interpolation"
    assert snapshot["sample_count"] == 1
    assert snapshot["normalized_threshold"] == 20
    assert snapshot["normalized_unit"] == "degC"
    assert snapshot["workflow_run_id"] == run["id"]
    assert snapshot["matches"][0]["record_id"] == record_ids[0]
    assert snapshot["matches"][0]["snapshot"]["record"]["id"] == record_ids[0]
    assert snapshot["matches"][0]["snapshot"]["record"]["provenance"]["source"] == (
        "laboratory sensor"
    )
    assert len(snapshot["matches"][0]["content_sha256"]) == 64
    assert len(result["payload_sha256"]) == 64
    history = client.get(records_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == len(record_ids)


def test_invalid_environmental_threshold_workflow_fails_without_artifact(
    client: TestClient,
) -> None:
    project = create_project(client, "Invalid environmental threshold")
    query = {**threshold_query(), "threshold_unit": "m/s"}
    run = save_and_queue(client, project["id"], threshold_graph(query))
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "environmental_threshold_samples"
        for artifact in detail.json()["artifacts"]
    )


def test_saved_environmental_threshold_graph_reuses_current_noaa_snapshot(
    client: TestClient,
) -> None:
    """Replaying one saved graph must not silently reuse superseded NOAA evidence."""
    from datetime import UTC, datetime, timedelta

    import httpx

    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.tests.test_environmental_context import noaa_fixture

    project = create_project(client, "Replayed NOAA threshold workflow")
    raw = noaa_fixture()
    raw["data"][0]["v"] = "21.0"
    import_request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    start = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        first_import = EnvironmentalContextService(
            session, http=http, now=start
        ).import_noaa(project["id"], import_request)
    first_record_id = str(first_import.items[0].id)

    graph = threshold_graph(threshold_query())
    saved_response = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved_response.status_code == 201, saved_response.text
    saved = saved_response.json()
    listed = client.get(f"/api/v1/projects/{project['id']}/workflow-graphs")
    assert listed.status_code == 200, listed.text
    assert any(
        item["id"] == saved["id"]
        and item["graph_sha256"] == saved["graph_sha256"]
        and item["graph_json"]["nodes"] == graph["nodes"]
        for item in listed.json()
    )

    def execute_saved_graph() -> tuple[dict, dict]:
        queued = client.post(
            f"/api/v1/projects/{project['id']}/workflow-runs",
            json={"graph_record_id": saved["id"]},
        )
        assert queued.status_code == 202, queued.text
        run = queued.json()
        app = cast(FastAPI, client.app)
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["graph_sha256"] == saved["graph_sha256"]
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "environmental_threshold_samples"
        )
        return run, artifact

    first_run, first_artifact = execute_saved_graph()
    assert first_artifact["payload_json"]["sample_count"] == 1
    assert first_artifact["payload_json"]["matches"][0]["record_id"] == first_record_id
    first_checksum = first_artifact["payload_sha256"]

    raw["data"][0]["v"] = "19.0"
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        refreshed = EnvironmentalContextService(
            session, http=http, now=start + timedelta(days=1)
        ).import_noaa(project["id"], import_request)
    assert str(refreshed.items[0].id) != first_record_id

    second_run, second_artifact = execute_saved_graph()
    assert second_run["workflow_graph_record_id"] == first_run["workflow_graph_record_id"]
    assert second_artifact["payload_json"]["sample_count"] == 0
    assert second_artifact["payload_json"]["matches"] == []

    persisted_first = client.get(f"/api/v1/workflow-runs/{first_run['id']}")
    assert persisted_first.status_code == 200, persisted_first.text
    original_artifact = next(
        item
        for item in persisted_first.json()["artifacts"]
        if item["data_type"] == "environmental_threshold_samples"
    )
    assert original_artifact["payload_sha256"] == first_checksum
    assert original_artifact["payload_json"]["matches"][0]["record_id"] == first_record_id
    history = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert history.status_code == 200, history.text
    old = next(item for item in history.json()["items"] if item["id"] == first_record_id)
    assert old["environmental_snapshot_current"] is False
