"""Saved Workflow Builder coverage must equal standalone 1.2 analysis."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def test_saved_workflow_preserves_missing_organism_ids(
    client: TestClient,
) -> None:
    project = create_project(client, "Longitudinal missing follow-up")
    project_id = str(project["id"])
    observations: list[dict[str, object]] = []
    for organism, day, value in (
        ("fragment-a", 1, 10),
        ("fragment-a", 2, 12),
        ("fragment-b", 1, 5),
    ):
        observations.append(
            {
                "organism_id": organism,
                "metric_name": "polyp_count",
                "source_record_id": f"{organism}-day-{day}",
                "observed_at": f"2026-04-0{day}T12:00:00Z",
                "value": value,
                "unit": "count",
                "experimental_unit_id": "tank-1",
                "experimental_unit_type": "tank",
            }
        )
    graph = _graph(observations)
    plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        item for item in detail.json()["artifacts"] if item["data_type"] == "longitudinal_analysis"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    standalone = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": observations},
    )
    assert standalone.status_code == 200, standalone.text
    assert payload["unit_coverage"] == standalone.json()["unit_coverage"]
    assert payload["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["unit_coverage"][0]["missing_organism_ids"] == ["fragment-b"]
    assert payload["unit_coverage"][0]["eligible_for_summary"] is False
    assert payload["unit_summaries"] == []
    assert payload["population_summaries"] == []
    assert payload["independent_unit_count"] == 1
    assert payload["analysis_provenance"]["algorithm_version"].startswith("ecology-longitudinal-")
