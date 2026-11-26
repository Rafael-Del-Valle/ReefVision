"""Immutable environmental definitions, QC filtering and saved graph integration."""

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models.scientific_record import EnvironmentalEventDefinition
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_data import observation
from reefvision.tests.test_workflow_computed_metrics import save_and_queue
from reefvision.tests.test_workflow_environmental_threshold import (
    threshold_graph,
    threshold_query,
)


def _create(client: TestClient, project_id: str) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/environment/events/definitions",
        json={"name": "Warm water", "query": threshold_query()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_saved_event_definition_evaluates_current_qc_evidence_and_is_project_scoped(
    client: TestClient,
) -> None:
    project = create_project(client, "Event definitions")
    other = create_project(client, "Foreign event project")
    saved = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={
            "records": [
                observation(value=21, unit="degC", qc="accepted"),
                observation(value=25, unit="degC", qc="suspect"),
                observation(value=19, unit="degC", qc="accepted"),
            ]
        },
    )
    assert saved.status_code == 201, saved.text
    accepted_id = saved.json()["items"][0]["id"]
    definition = _create(client, project["id"])
    base = f"/api/v1/projects/{project['id']}/environment/events/definitions"
    assert client.get(f"{base}/{definition['id']}").json() == definition
    listed = client.get(base)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"] == [definition]
    evaluated = client.post(f"{base}/{definition['id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    result = evaluated.json()
    assert result["definition_sha256"] == definition["definition_sha256"]
    assert result["result"]["normalized_threshold"] == 20
    assert result["result"]["method"] == "observed_sample_threshold_no_interpolation"
    assert [m["record"]["id"] for m in result["result"]["matches"]] == [accepted_id]
    foreign = f"/api/v1/projects/{other['id']}/environment/events/definitions"
    assert client.get(f"{foreign}/{definition['id']}").status_code == 404
    assert client.post(f"{foreign}/{definition['id']}/evaluate").status_code == 404


def test_saved_workflow_references_event_definition_and_persists_provenance(
    client: TestClient,
) -> None:
    project = create_project(client, "Event graph")
    saved = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={"records": [observation(value=22, unit="degC", qc="accepted")]},
    )
    assert saved.status_code == 201, saved.text
    record_id = saved.json()["items"][0]["id"]
    definition = _create(client, project["id"])
    run = save_and_queue(
        client, project["id"], threshold_graph({"definition_id": definition["id"]})
    )
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
        if item["data_type"] == "environmental_threshold_samples"
    )
    payload = artifact["payload_json"]
    assert payload["definition_id"] == definition["id"]
    assert payload["definition_sha256"] == definition["definition_sha256"]
    assert payload["query"] == definition["query"]
    assert payload["sample_count"] == 1
    assert payload["matches"][0]["record_id"] == record_id
    assert len(artifact["payload_sha256"]) == 64


def test_invalid_event_units_and_tampered_definition_are_rejected(
    client: TestClient,
) -> None:
    project = create_project(client, "Event validation")
    base = f"/api/v1/projects/{project['id']}/environment/events/definitions"
    bad = client.post(
        base,
        json={"name": "Invalid", "query": {**threshold_query(), "threshold_unit": "m/s"}},
    )
    assert bad.status_code == 400, bad.text
    assert client.get(base).json()["total"] == 0
    definition = _create(client, project["id"])
    with client.app.state.session_factory() as session:
        row = session.get(EnvironmentalEventDefinition, definition["id"])
        assert row is not None
        row.query_json = {**row.query_json, "threshold_value": 99}
        session.commit()
    assert client.get(f"{base}/{definition['id']}").status_code == 409
    assert client.post(f"{base}/{definition['id']}/evaluate").status_code == 409


def test_saved_event_definition_replay_preserves_historical_evidence(
    client: TestClient,
) -> None:
    """Re-execution uses current QC evidence without rewriting the named rule or old run."""
    project = create_project(client, "Event definition replay")
    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    initial = client.post(
        records_url,
        json={"records": [observation(value=19, unit="degC", qc="accepted")]},
    )
    assert initial.status_code == 201, initial.text
    definition = _create(client, project["id"])
    first = save_and_queue(
        client, project["id"], threshold_graph({"definition_id": definition["id"]})
    )
    app = cast(FastAPI, client.app)

    def read_artifact(run: dict) -> dict:
        detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        return next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "environmental_threshold_samples"
        )

    def execute(run: dict) -> dict:
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run["job_id"])
        )
        return read_artifact(run)

    historical = execute(first)
    assert historical["payload_json"]["sample_count"] == 0
    assert historical["payload_json"]["matches"] == []
    assert historical["payload_json"]["definition_sha256"] == definition["definition_sha256"]

    added = client.post(
        records_url,
        json={
            "records": [
                observation(value=22, unit="degC", qc="accepted"),
                observation(value=25, unit="degC", qc="suspect"),
            ]
        },
    )
    assert added.status_code == 201, added.text
    accepted_id = added.json()["items"][0]["id"]
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": first["workflow_graph_record_id"]},
    )
    assert queued.status_code == 202, queued.text
    second = queued.json()
    assert second["workflow_graph_record_id"] == first["workflow_graph_record_id"]
    current = execute(second)
    payload = current["payload_json"]
    assert payload["definition_id"] == definition["id"]
    assert payload["definition_sha256"] == definition["definition_sha256"]
    assert payload["query"] == definition["query"]
    assert payload["workflow_run_id"] == second["id"]
    assert payload["sample_count"] == 1
    assert [match["record_id"] for match in payload["matches"]] == [accepted_id]
    assert current["payload_sha256"] != historical["payload_sha256"]
    original = read_artifact(first)
    assert original["payload_sha256"] == historical["payload_sha256"]
    assert original["payload_json"] == historical["payload_json"]
    base = f"/api/v1/projects/{project['id']}/environment/events/definitions"
    assert client.get(f"{base}/{definition['id']}").json() == definition

def test_saved_event_definition_respects_observation_context_bounds(
    client: TestClient,
) -> None:
    """A threshold crossing is evidence only within the saved sampling context."""
    project = create_project(client, "Bounded environmental event")
    base = f"/api/v1/projects/{project['id']}/environment/events/definitions"
    query = {
        **threshold_query(),
        "depth_m": 10,
        "depth_reference": "sea_surface",
        "max_depth_delta_m": 2,
    }
    response = client.post(base, json={"name": "Depth-bounded warm water", "query": query})
    assert response.status_code == 201, response.text
    definition = response.json()
    run = save_and_queue(
        client, project["id"], threshold_graph({"definition_id": definition["id"]})
    )

    def sample(**overrides) -> dict:
        return observation(
            **{
                "value": 22,
                "unit": "degC",
                "qc": "accepted",
                "depth_m": 12,
                "depth_reference": "sea_surface",
                **overrides,
            }
        )

    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    saved = client.post(
        records_url,
        json={
            "records": [
                sample(observed_at="2026-04-03T13:01:00Z"),
                sample(observed_at="2026-04-03T13:01:01Z"),
                sample(depth_m=12.1),
                sample(depth_reference="chart_datum"),
                sample(depth_m=None, depth_reference=None),
                sample(location={"latitude": 33.0, "longitude": -79.93}),
                sample(location=None),
                sample(source_kind="modeled"),
                sample(qc="rejected"),
            ]
        },
    )
    assert saved.status_code == 201, saved.text
    accepted_id = saved.json()["items"][0]["id"]
    direct = client.post(f"{base}/{definition['id']}/evaluate")
    assert direct.status_code == 200, direct.text
    matches = direct.json()["result"]["matches"]
    assert [match["record"]["id"] for match in matches] == [accepted_id]
    assert matches[0]["time_delta_s"] == 60
    assert matches[0]["depth_delta_m"] == 2

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
        if item["data_type"] == "environmental_threshold_samples"
    )
    payload = artifact["payload_json"]
    assert payload["definition_sha256"] == definition["definition_sha256"]
    assert payload["query"] == definition["query"]
    assert payload["sample_count"] == 1
    assert [match["record_id"] for match in payload["matches"]] == [accepted_id]
    assert len(artifact["payload_sha256"]) == 64
    assert client.get(records_url).json()["total"] == 9

