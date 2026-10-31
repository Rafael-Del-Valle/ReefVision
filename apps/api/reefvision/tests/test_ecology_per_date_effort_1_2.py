"""Per-date ecological sampling effort through standalone and saved workflows."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_sampling_schedule_1_2 import _payload
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def test_per_date_coverage_counts_missing_organisms_not_mortality(
    client: TestClient,
) -> None:
    request = _payload(missing=True)
    request["expected_organism_ids_by_unit"] = {"tank-1": ["A", "B", "C"]}
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    rows = body["planned_sampling_date_coverage"]
    assert [row["sampling_date"] for row in rows] == ["2026-04-01", "2026-04-02", "2026-04-03"]
    assert [row["observed_organism_ids"] for row in rows] == [["A", "B"], ["A"], ["A", "B"]]
    assert [row["missing_organism_ids"] for row in rows] == [["C"], ["B", "C"], ["C"]]
    assert [row["expected_organism_count"] for row in rows] == [3, 3, 3]
    assert [row["observed_organism_count"] for row in rows] == [2, 1, 2]
    assert [row["observation_coverage_fraction"] for row in rows] == pytest.approx(
        [2 / 3, 1 / 3, 2 / 3]
    )
    assert all(row["expected_roster_supplied"] for row in rows)
    assert (
        sum(row["observed_organism_count"] for row in rows)
        == (body["planned_sampling_effort"][0]["observed_organism_visits"])
    )
    assert body["evidence_level"] == "caller_supplied_unverified"
    assert body["population_summaries"] == []


def test_without_roster_denominator_is_only_observed_organisms(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=_payload(True))
    assert response.status_code == 200, response.text
    rows = response.json()["planned_sampling_date_coverage"]
    assert [row["expected_organism_count"] for row in rows] == [2, 2, 2]
    assert [row["missing_organism_ids"] for row in rows] == [[], ["B"], []]
    assert all(not row["expected_roster_supplied"] for row in rows)


def test_unscheduled_study_has_no_invented_visit_denominators(
    client: TestClient,
) -> None:
    request = _payload()
    request.pop("expected_sampling_dates_by_unit")
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["planned_sampling_date_coverage"] == []


def test_saved_workflow_persists_identical_per_date_scientific_qc(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Per-date sampling QC")["id"])
    request = _payload(missing=True)
    request["expected_organism_ids_by_unit"] = {"tank-1": ["A", "B", "C"]}
    graph: dict[str, Any] = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update(
        {
            "experimental_unit_type": "tank",
            "expected_sampling_dates_by_unit": request["expected_sampling_dates_by_unit"],
            "expected_organism_ids_by_unit": request["expected_organism_ids_by_unit"],
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
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        row for row in detail.json()["artifacts"] if row["data_type"] == "longitudinal_analysis"
    ]
    assert len(artifacts) == 1
    standalone = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert standalone.status_code == 200, standalone.text
    persisted = artifacts[0]["payload_json"]
    assert (
        persisted["planned_sampling_date_coverage"]
        == (standalone.json()["planned_sampling_date_coverage"])
    )
    assert persisted["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert persisted["evidence_level"] == "caller_supplied_unverified"
