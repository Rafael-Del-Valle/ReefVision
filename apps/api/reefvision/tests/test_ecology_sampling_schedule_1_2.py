"""Scheduled UTC sampling QC for standalone and persisted 1.2 ecology workflows."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _payload(missing: bool = False) -> dict[str, Any]:
    rows = []
    for organism in ("A", "B"):
        for day in ((1, 3) if missing and organism == "B" else (1, 2, 3)):
            rows.append({
                "organism_id": organism,
                "metric_name": "polyp_count",
                "source_record_id": f"{organism}-{day}",
                "observed_at": f"2026-04-0{day}T12:00:00Z",
                "value": 10 + day,
                "unit": "count",
                "experimental_unit_id": "tank-1",
            })
    return {
        "observations": rows,
        "experimental_unit_type": "tank",
        "expected_sampling_dates_by_unit": {
            "tank-1": ["2026-04-03", "2026-04-01", "2026-04-02"]
        },
    }


def test_complete_calendar_retains_one_tank(client: TestClient) -> None:
    result = client.post("/api/v1/ecology/longitudinal-analysis", json=_payload())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["evidence_level"] == "caller_supplied_unverified"
    assert body["expected_sampling_schedule_supplied"] is True
    assert body["analysis_provenance"]["algorithm_version"] == "ecology-longitudinal-0009"
    assert body["population_summaries"][0]["independent_unit_count"] == 1
    assert body["unit_coverage"][0]["missing_scheduled_dates_by_organism"] == {}


def test_missing_intermediate_visit_excludes_tank_without_claiming_mortality(
    client: TestClient,
) -> None:
    result = client.post("/api/v1/ecology/longitudinal-analysis", json=_payload(True))
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["evaluated_series_count"] == 2
    assert body["unit_summaries"] == []
    assert body["population_summaries"] == []
    assert body["independent_unit_count"] == 1
    assert body["unit_coverage"][0]["exclusion_reason"] == "missing_scheduled_observations"
    assert body["unit_coverage"][0]["missing_scheduled_dates_by_organism"] == {
        "B": ["2026-04-02"]
    }


@pytest.mark.parametrize(
    ("calendar", "message"),
    [
        ({"tank-2": ["2026-04-01", "2026-04-03"]}, "exactly the observed units"),
        ({"tank-1": ["2026-04-01"]}, "at least two UTC dates"),
        ({"tank-1": ["2026-04-01", "2026-04-01"]}, "duplicate UTC dates"),
        ({"tank-1": ["2026-04-01", "2026-04-03"]}, "outside the expected"),
    ],
)
def test_invalid_calendars_fail_closed(
    client: TestClient, calendar: dict[str, list[str]], message: str
) -> None:
    request = _payload()
    request["expected_sampling_dates_by_unit"] = calendar
    result = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert result.status_code == 400, result.text
    assert message in result.json()["detail"]


def test_calendar_and_observation_order_do_not_change_provenance(client: TestClient) -> None:
    request = _payload()
    first = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert first.status_code == 200, first.text
    request["observations"].reverse()
    request["expected_sampling_dates_by_unit"]["tank-1"].reverse()
    second = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert second.status_code == 200, second.text
    assert first.json()["analysis_provenance"] == second.json()["analysis_provenance"]


def test_saved_workflow_persists_schedule_qc(client: TestClient) -> None:
    project_id = str(create_project(client, "Scheduled visits")["id"])
    request = _payload(True)
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update({
        "experimental_unit_type": "tank",
        "expected_sampling_dates_by_unit": request["expected_sampling_dates_by_unit"],
    })
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
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    ) is True
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        item for item in detail.json()["artifacts"]
        if item["data_type"] == "longitudinal_analysis"
    ]
    assert len(artifacts) == 1
    standalone = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert standalone.status_code == 200, standalone.text
    assert artifacts[0]["payload_json"]["unit_coverage"] == standalone.json()["unit_coverage"]
    assert artifacts[0]["payload_json"]["analysis_provenance"] == standalone.json()[
        "analysis_provenance"
    ]
    assert artifacts[0]["payload_json"]["evidence_level"] == "caller_supplied_unverified"


def test_invalid_saved_calendar_does_not_produce_successful_analysis(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Invalid planned visits")["id"])
    request = _payload()
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update({
        "experimental_unit_type": "tank",
        "expected_sampling_dates_by_unit": {
            "tank-1": ["2026-04-01", "2026-04-03"]
        },
    })
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
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    ) is False
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "longitudinal_analysis"
        for item in detail.json()["artifacts"]
    )
