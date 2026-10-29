"""Saved environmental-event graphs fail closed on altered or foreign definitions."""

from typing import cast

import pytest
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


def _definition(client: TestClient, project_id: str) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/environment/events/definitions",
        json={"name": "Temperature threshold", "query": threshold_query()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _accepted_temperature(client: TestClient, project_id: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/scientific-records",
        json={"records": [observation(value=22, unit="degC", qc="accepted")]},
    )
    assert response.status_code == 201, response.text


def _assert_failed_without_threshold_artifact(client: TestClient, run: dict) -> None:
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "environmental_threshold_samples"
        for item in detail.json()["artifacts"]
    )


@pytest.mark.parametrize("altered_field", ["name", "query_json"])
def test_saved_event_graph_rejects_tampered_definition_without_artifact(
    client: TestClient, altered_field: str
) -> None:
    """The graph is saved first; corruption must be detected at execution time."""
    project = create_project(client, f"Tampered event {altered_field}")
    _accepted_temperature(client, project["id"])
    definition = _definition(client, project["id"])
    run = save_and_queue(
        client, project["id"], threshold_graph({"definition_id": definition["id"]})
    )
    with client.app.state.session_factory() as session:
        row = session.get(EnvironmentalEventDefinition, definition["id"])
        assert row is not None
        if altered_field == "name":
            row.name = "Modified without a new definition"
        else:
            row.query_json = {**row.query_json, "threshold_value": 99}
        session.commit()

    base = f"/api/v1/projects/{project['id']}/environment/events/definitions"
    assert client.get(f"{base}/{definition['id']}").status_code == 409
    _assert_failed_without_threshold_artifact(client, run)


def test_saved_event_graph_rejects_foreign_project_definition_without_artifact(
    client: TestClient,
) -> None:
    """A valid definition cannot be reused across unrelated project boundaries."""
    source = create_project(client, "Source event project")
    destination = create_project(client, "Destination event project")
    definition = _definition(client, source["id"])
    _accepted_temperature(client, destination["id"])
    run = save_and_queue(
        client,
        destination["id"],
        threshold_graph({"definition_id": definition["id"]}),
    )
    _assert_failed_without_threshold_artifact(client, run)

    original = client.get(
        f"/api/v1/projects/{source['id']}/environment/events/definitions/{definition['id']}"
    )
    assert original.status_code == 200, original.text
    assert original.json()["definition_sha256"] == definition["definition_sha256"]
