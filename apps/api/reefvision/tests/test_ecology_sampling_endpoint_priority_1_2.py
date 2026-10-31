"""Missing planned endpoint visits must be visible in ecological QC and workflows."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_sampling_schedule_1_2 import _payload
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _missing_first_visit() -> dict:
    request = _payload()
    request["observations"] = [
        row for row in request["observations"] if row["source_record_id"] != "B-1"
    ]
    return request


def test_missing_planned_endpoint_reports_calendar_qc_not_window_qc(
    client: TestClient,
) -> None:
    request = _missing_first_visit()
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence_level"] == "caller_supplied_unverified"
    assert body["analysis_provenance"]["algorithm_version"] == ("ecology-longitudinal-0012")
    assert body["unit_summaries"] == []
    assert body["planned_sampling_effort"][0]["expected_organism_visits"] == 6
    assert body["planned_sampling_effort"][0]["observed_organism_visits"] == 5
    assert body["planned_sampling_effort"][0]["missing_organism_visits"] == 1
    assert body["population_summaries"] == []
    assert body["excluded_units"][0]["reason"] == "missing_scheduled_observations"
    coverage = body["unit_coverage"][0]
    assert coverage["exclusion_reason"] == "missing_scheduled_observations"
    assert coverage["missing_scheduled_dates_by_organism"] == {"B": ["2026-04-01"]}
    assert coverage["complete_organism_count"] == 2
    assert coverage["eligible_for_summary"] is False

    request.pop("expected_sampling_dates_by_unit")
    legacy = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["excluded_units"][0]["reason"] == "nonmatching_sampling_window"
    assert legacy.json()["analysis_provenance"]["algorithm_version"] == (
        "ecology-longitudinal-0008"
    )


def test_missing_planned_endpoint_persists_same_qc_in_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Missing scheduled endpoint")["id"])
    request = _missing_first_visit()
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update(
        {
            "experimental_unit_type": "tank",
            "expected_sampling_dates_by_unit": request["expected_sampling_dates_by_unit"],
        }
    )
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
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
    standalone = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert standalone.status_code == 200, standalone.text
    payload = artifacts[0]["payload_json"]
    result = standalone.json()
    assert payload["unit_coverage"] == result["unit_coverage"]
    assert payload["planned_sampling_effort"] == result["planned_sampling_effort"]
    assert payload["excluded_units"] == result["excluded_units"]
    assert payload["analysis_provenance"] == result["analysis_provenance"]


def _singleton_on_planned_calendar() -> dict:
    request = _payload()
    request["observations"] = [
        row
        for row in request["observations"]
        if row["organism_id"] != "B" or row["source_record_id"] == "B-1"
    ]
    return request


def test_scheduled_singleton_reports_missing_visits_and_incomplete_followup(
    client: TestClient,
) -> None:
    request = _singleton_on_planned_calendar()
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence_level"] == "caller_supplied_unverified"
    assert body["analysis_provenance"]["algorithm_version"] == ("ecology-longitudinal-0012")
    assert body["evaluated_series_count"] == 1
    assert body["incomplete_series_count"] == 1
    assert body["unit_summaries"] == []
    assert body["population_summaries"] == []
    assert body["excluded_units"][0]["reason"] == "missing_scheduled_observations"
    coverage = body["unit_coverage"][0]
    assert coverage["exclusion_reason"] == "missing_scheduled_observations"
    assert coverage["complete_organism_count"] == 1
    assert coverage["missing_followup_organism_count"] == 1
    assert coverage["missing_organism_ids"] == ["B"]
    assert coverage["missing_scheduled_dates_by_organism"] == {"B": ["2026-04-02", "2026-04-03"]}
    effort = body["planned_sampling_effort"][0]
    assert effort["expected_organism_visits"] == 6
    assert effort["observed_organism_visits"] == 4
    assert effort["missing_organism_visits"] == 2
    assert effort["observation_coverage_fraction"] == 4 / 6

    request.pop("expected_sampling_dates_by_unit")
    legacy = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["excluded_units"][0]["reason"] == "missing_followup"
    assert legacy.json()["analysis_provenance"]["algorithm_version"] == (
        "ecology-longitudinal-0008"
    )


def test_scheduled_singleton_saved_workflow_matches_standalone_qc(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Singleton planned visits")["id"])
    request = _singleton_on_planned_calendar()
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update(
        {
            "experimental_unit_type": "tank",
            "expected_sampling_dates_by_unit": request["expected_sampling_dates_by_unit"],
        }
    )
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
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
    standalone = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert standalone.status_code == 200, standalone.text
    payload = artifacts[0]["payload_json"]
    result = standalone.json()
    assert payload["unit_coverage"] == result["unit_coverage"]
    assert payload["planned_sampling_effort"] == result["planned_sampling_effort"]
    assert payload["excluded_units"] == result["excluded_units"]
    assert payload["analysis_provenance"] == result["analysis_provenance"]
    assert payload["evidence_level"] == "caller_supplied_unverified"
