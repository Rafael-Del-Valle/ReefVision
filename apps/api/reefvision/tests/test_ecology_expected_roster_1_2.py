"""Expected-roster completeness and saved-workflow provenance for ReefVision 1.2."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _observations() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for organism, tank, values in (
        ("frag-A", "tank-1", (10, 12)),
        ("frag-B", "tank-2", (20, 25)),
    ):
        for day, value in enumerate(values, 1):
            rows.append(
                {
                    "organism_id": organism,
                    "metric_name": "polyp_count",
                    "source_record_id": f"{organism}-{day}",
                    "observed_at": f"2026-04-0{day}T12:00:00Z",
                    "value": value,
                    "unit": "count",
                    "experimental_unit_id": tank,
                }
            )
    return rows


def _roster() -> dict[str, list[str]]:
    return {"tank-1": ["frag-C", "frag-A"], "tank-2": ["frag-B"]}


def test_standalone_roster_excludes_unobserved_organism_without_claiming_death(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={
            "observations": _observations(),
            "experimental_unit_type": "tank",
            "expected_organism_ids_by_unit": _roster(),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["expected_roster_supplied"] is True
    assert payload["independent_unit_count"] == 2
    assert payload["analysis_provenance"]["algorithm_version"] == "ecology-longitudinal-0008"
    assert payload["unit_coverage"][0]["unobserved_organism_ids"] == ["frag-C"]
    assert payload["unit_coverage"][0]["expected_organism_count"] == 2
    assert payload["unit_coverage"][0]["missing_organism_ids"] == []
    assert payload["unit_coverage"][0]["exclusion_reason"] == "missing_expected_organisms"
    assert payload["unit_coverage"][1]["eligible_for_summary"] is True
    assert [row["experimental_unit_id"] for row in payload["unit_summaries"]] == ["tank-2"]
    assert payload["population_summaries"][0]["independent_unit_count"] == 1


def test_roster_order_does_not_change_fingerprint(client: TestClient) -> None:
    request = {
        "observations": _observations(),
        "experimental_unit_type": "tank",
        "expected_organism_ids_by_unit": _roster(),
    }
    first = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert first.status_code == 200, first.text
    request["expected_organism_ids_by_unit"] = {
        "tank-2": ["frag-B"],
        "tank-1": ["frag-A", "frag-C"],
    }
    second = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert second.status_code == 200, second.text
    assert first.json()["analysis_provenance"] == second.json()["analysis_provenance"]


@pytest.mark.parametrize(
    ("roster", "error"),
    [
        ({"tank-1": ["frag-A"]}, "exactly the observed units"),
        ({"tank-1": ["frag-A"], "tank-2": ["frag-A", "frag-B"]}, "multiple units"),
        ({"tank-1": ["frag-A"], "tank-2": ["frag-X"]}, "absent from"),
        ({"tank-1": ["frag-A"], "tank-2": ["frag-B", "frag-B"]}, "duplicate"),
        ({"tank-1": ["frag-A"], "tank-2": []}, "empty unit"),
    ],
)
def test_standalone_rejects_invalid_rosters(
    client: TestClient, roster: dict[str, list[str]], error: str
) -> None:
    response = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={
            "observations": _observations(),
            "experimental_unit_type": "tank",
            "expected_organism_ids_by_unit": roster,
        },
    )
    assert response.status_code == 400, response.text
    assert error in response.json()["detail"]


def test_saved_workflow_roster_coverage_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "Expected roster QC")["id"])
    graph = _graph(_observations())
    graph["nodes"][1]["parameters"].update(
        {"experimental_unit_type": "tank", "expected_organism_ids_by_unit": _roster()}
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
        row for row in detail.json()["artifacts"] if row["data_type"] == "longitudinal_analysis"
    ]
    assert len(artifacts) == 1
    standalone = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={
            "observations": _observations(),
            "experimental_unit_type": "tank",
            "expected_organism_ids_by_unit": _roster(),
        },
    )
    assert standalone.status_code == 200, standalone.text
    assert artifacts[0]["payload_json"]["unit_coverage"] == standalone.json()["unit_coverage"]
    assert (
        artifacts[0]["payload_json"]["analysis_provenance"]
        == standalone.json()["analysis_provenance"]
    )
    assert artifacts[0]["payload_json"]["evidence_level"] == "caller_supplied_unverified"
