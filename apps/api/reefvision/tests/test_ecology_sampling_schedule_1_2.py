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
        for day in (1, 3) if missing and organism == "B" else (1, 2, 3):
            rows.append(
                {
                    "organism_id": organism,
                    "metric_name": "polyp_count",
                    "source_record_id": f"{organism}-{day}",
                    "observed_at": f"2026-04-0{day}T12:00:00Z",
                    "value": 10 + day,
                    "unit": "count",
                    "experimental_unit_id": "tank-1",
                }
            )
    return {
        "observations": rows,
        "experimental_unit_type": "tank",
        "expected_sampling_dates_by_unit": {"tank-1": ["2026-04-03", "2026-04-01", "2026-04-02"]},
    }


def test_complete_calendar_retains_one_tank(client: TestClient) -> None:
    result = client.post("/api/v1/ecology/longitudinal-analysis", json=_payload())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["evidence_level"] == "caller_supplied_unverified"
    assert body["expected_sampling_schedule_supplied"] is True
    assert body["analysis_provenance"]["algorithm_version"] == "ecology-longitudinal-0012"
    assert body["population_summaries"][0]["independent_unit_count"] == 1
    assert body["unit_coverage"][0]["missing_scheduled_dates_by_organism"] == {}
    effort = body["planned_sampling_effort"]
    assert len(effort) == 1
    assert effort[0]["expected_organism_visits"] == 6
    assert effort[0]["observed_organism_visits"] == 6
    assert effort[0]["missing_organism_visits"] == 0
    assert effort[0]["observation_coverage_fraction"] == 1.0
    assert effort[0]["expected_roster_supplied"] is False


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
    assert body["unit_coverage"][0]["missing_scheduled_dates_by_organism"] == {"B": ["2026-04-02"]}
    effort = body["planned_sampling_effort"][0]
    assert effort["expected_organism_visits"] == 6
    assert effort["observed_organism_visits"] == 5
    assert effort["missing_organism_visits"] == 1
    assert effort["observation_coverage_fraction"] == pytest.approx(5 / 6)


def test_expected_roster_counts_completely_unobserved_organism_visits(
    client: TestClient,
) -> None:
    request = _payload(missing=True)
    request["expected_organism_ids_by_unit"] = {"tank-1": ["A", "B", "C"]}
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unit_summaries"] == []
    assert body["unit_coverage"][0]["unobserved_organism_ids"] == ["C"]
    effort = body["planned_sampling_effort"][0]
    assert effort["expected_roster_supplied"] is True
    assert effort["expected_organism_count"] == 3
    assert effort["expected_organism_visits"] == 9
    assert effort["observed_organism_visits"] == 5
    assert effort["missing_organism_visits"] == 4
    assert effort["observation_coverage_fraction"] == pytest.approx(5 / 9)
    assert body["evidence_level"] == "caller_supplied_unverified"


def test_unscheduled_legacy_analysis_has_no_planned_effort(
    client: TestClient,
) -> None:
    request = _payload()
    request.pop("expected_sampling_dates_by_unit")
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["planned_sampling_effort"] == []
    assert response.json()["analysis_provenance"]["algorithm_version"] == (
        "ecology-longitudinal-0008"
    )


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
    assert artifacts[0]["payload_json"]["unit_coverage"] == standalone.json()["unit_coverage"]
    assert (
        artifacts[0]["payload_json"]["planned_sampling_effort"]
        == standalone.json()["planned_sampling_effort"]
    )
    assert (
        artifacts[0]["payload_json"]["analysis_provenance"]
        == standalone.json()["analysis_provenance"]
    )
    assert artifacts[0]["payload_json"]["evidence_level"] == "caller_supplied_unverified"


def test_invalid_saved_calendar_does_not_produce_successful_analysis(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Invalid planned visits")["id"])
    request = _payload()
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update(
        {
            "experimental_unit_type": "tank",
            "expected_sampling_dates_by_unit": {"tank-1": ["2026-04-01", "2026-04-03"]},
        }
    )
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
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "longitudinal_analysis" for item in detail.json()["artifacts"]
    )


@pytest.mark.parametrize(
    "invalid_date",
    [1743465600, "2026-04-01T00:00:00Z", True, "2026-4-1"],
)
def test_calendar_requires_explicit_iso_calendar_dates(
    client: TestClient, invalid_date: object
) -> None:
    request = _payload()
    request["expected_sampling_dates_by_unit"]["tank-1"][0] = invalid_date
    result = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert result.status_code == 422, result.text
    assert "explicit ISO YYYY-MM-DD" in result.text


def test_scheduled_analysis_requires_unit_ids_for_every_observation(
    client: TestClient,
) -> None:
    request = _payload()
    request["observations"][0].pop("experimental_unit_id")
    result = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert result.status_code == 400, result.text
    assert "requires unit IDs on all observations" in result.json()["detail"]


def test_missing_scheduled_unit_id_fails_saved_workflow_without_analysis_artifact(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Missing sampling unit ID")["id"])
    request = _payload()
    request["observations"][0].pop("experimental_unit_id")
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update(
        {
            "experimental_unit_type": "tank",
            "expected_sampling_dates_by_unit": request["expected_sampling_dates_by_unit"],
        }
    )
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
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "longitudinal_analysis" for item in detail.json()["artifacts"]
    )
