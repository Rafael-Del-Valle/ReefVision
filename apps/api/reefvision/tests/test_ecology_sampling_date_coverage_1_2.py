"""Per-organism UTC sampling-date coverage in standalone and saved ecological analyses."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _observations(*, discordant: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for organism in ("frag-A", "frag-B"):
        days = (1, 2, 3) if organism == "frag-A" or not discordant else (1, 3)
        for day in days:
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
    return rows


def _request(discordant: bool) -> dict[str, Any]:
    return {
        "observations": _observations(discordant=discordant),
        "experimental_unit_type": "tank",
    }


def test_intermediate_sampling_date_gap_is_disclosed_without_false_exclusion(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=_request(True))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["evidence_level"] == "caller_supplied_unverified"
    assert result["analysis_provenance"]["algorithm_version"] == "ecology-longitudinal-0008"
    assert result["independent_unit_count"] == 1
    assert len(result["unit_summaries"]) == 1
    assert result["excluded_units"] == []
    coverage = result["unit_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["eligible_for_summary"] is True
    assert coverage[0]["discordant_sampling_dates"] is True
    assert coverage[0]["observed_sampling_dates_by_organism"] == {
        "frag-A": ["2026-04-01", "2026-04-02", "2026-04-03"],
        "frag-B": ["2026-04-01", "2026-04-03"],
    }
    assert any("intermediate observation dates" in text for text in result["limitations"])


def test_equal_sampling_dates_have_no_false_discordance(client: TestClient) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=_request(False))
    assert response.status_code == 200, response.text
    assert response.json()["unit_coverage"][0]["discordant_sampling_dates"] is False


def test_sampling_date_qc_uses_utc_not_camera_local_date(client: TestClient) -> None:
    payload = _request(False)
    for observation in payload["observations"]:
        if observation["organism_id"] == "frag-B":
            day = int(observation["observed_at"][9:10])
            observation["observed_at"] = f"2026-04-0{day + 1}T00:30:00+02:00"
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=payload)
    assert response.status_code == 200, response.text
    coverage = response.json()["unit_coverage"][0]
    assert coverage["discordant_sampling_dates"] is False
    assert coverage["observed_sampling_dates_by_organism"]["frag-B"] == [
        "2026-04-01",
        "2026-04-02",
        "2026-04-03",
    ]


def test_sampling_date_qc_is_deterministic_and_persisted_in_saved_workflow(
    client: TestClient,
) -> None:
    payload = _request(True)
    first = client.post("/api/v1/ecology/longitudinal-analysis", json=payload)
    assert first.status_code == 200, first.text
    reversed_payload = {**payload, "observations": list(reversed(payload["observations"]))}
    second = client.post("/api/v1/ecology/longitudinal-analysis", json=reversed_payload)
    assert second.status_code == 200, second.text
    assert first.json()["analysis_provenance"] == second.json()["analysis_provenance"]
    assert first.json()["unit_coverage"] == second.json()["unit_coverage"]

    project_id = str(create_project(client, "Sampling date QC")["id"])
    graph = _graph(payload["observations"])
    graph["nodes"][1]["parameters"]["experimental_unit_type"] = "tank"
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
    assert artifacts[0]["payload_json"]["unit_coverage"] == first.json()["unit_coverage"]
    assert (
        artifacts[0]["payload_json"]["analysis_provenance"] == first.json()["analysis_provenance"]
    )
    assert artifacts[0]["payload_json"]["evidence_level"] == "caller_supplied_unverified"
