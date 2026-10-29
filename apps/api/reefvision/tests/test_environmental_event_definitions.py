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
    assert bad.status_code == 422, bad.text
    assert client.get(base).json()["total"] == 0
    definition = _create(client, project["id"])
    with client.app.state.session_factory() as session:
        row = session.get(EnvironmentalEventDefinition, definition["id"])
        assert row is not None
        row.query_json = {**row.query_json, "threshold_value": 99}
        session.commit()
    assert client.get(f"{base}/{definition['id']}").status_code == 409
    assert client.post(f"{base}/{definition['id']}/evaluate").status_code == 409
