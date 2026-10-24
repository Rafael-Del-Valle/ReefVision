"""UTC sampling-date alignment for independent ecological experimental units."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _obs(organism: str, source: str, observed_at: str, value: float) -> dict[str, object]:
    return {
        "organism_id": organism,
        "metric_name": "polyp_count",
        "source_record_id": source,
        "observed_at": observed_at,
        "value": value,
        "unit": "count",
        "experimental_unit_id": "tank-A",
        "experimental_unit_type": "tank",
    }


def _same_date_observations() -> list[dict[str, object]]:
    return [
        _obs("frag-A", "a-first", "2026-04-01T08:00:00Z", 10),
        _obs("frag-A", "a-last", "2026-04-03T11:00:00Z", 12),
        _obs("frag-B", "b-first", "2026-04-01T16:00:00Z", 20),
        _obs("frag-B", "b-last", "2026-04-03T18:00:00Z", 24),
    ]


def test_same_utc_dates_different_hours_are_eligible() -> None:
    result = analyze_longitudinal(
        LongitudinalAnalysisRequest(observations=_same_date_observations())
    )
    assert result.evaluated_series_count == 2
    assert result.independent_unit_count == 1
    assert result.excluded_units == []
    assert result.unit_coverage[0].eligible_for_summary is True
    assert result.unit_summaries[0].organism_count == 2
    assert result.unit_summaries[0].mean_absolute_change == 3
    assert result.unit_summaries[0].baseline_at.isoformat() == ("2026-04-01T08:00:00+00:00")
    assert result.unit_summaries[0].final_at.isoformat() == ("2026-04-03T18:00:00+00:00")
    assert result.population_summaries[0].independent_unit_count == 1
    assert result.analysis_provenance.algorithm_version.startswith("ecology-longitudinal-")
    assert result.evidence_level == "caller_supplied_unverified"


def test_timezone_offsets_are_normalized_before_window_comparison() -> None:
    observations = _same_date_observations()
    observations[2]["observed_at"] = "2026-03-31T23:30:00-04:00"
    observations[3]["observed_at"] = "2026-04-03T14:00:00-04:00"
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert len(result.unit_summaries) == 1
    assert result.unit_summaries[0].baseline_at.isoformat() == ("2026-04-01T03:30:00+00:00")
    assert result.unit_summaries[0].final_at.isoformat() == ("2026-04-03T18:00:00+00:00")


def test_different_utc_sampling_dates_still_exclude_unit() -> None:
    observations = _same_date_observations()
    observations[2]["observed_at"] = "2026-04-02T08:00:00Z"
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert result.unit_summaries == []
    assert result.population_summaries == []
    assert result.excluded_units[0].reason == "nonmatching_sampling_window"
    assert result.unit_coverage[0].eligible_for_summary is False


def test_standalone_and_saved_workflow_agree_on_date_window(
    client: TestClient,
) -> None:
    observations = _same_date_observations()
    standalone = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": observations},
    )
    assert standalone.status_code == 200, standalone.text
    assert standalone.json()["unit_summaries"][0]["organism_count"] == 2

    project = create_project(client, "UTC-date ecological sampling")
    project_id = str(project["id"])
    graph = _graph(observations)
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
    assert payload["unit_summaries"] == standalone.json()["unit_summaries"]
    assert payload["unit_coverage"] == standalone.json()["unit_coverage"]
    assert payload["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert payload["evidence_level"] == "caller_supplied_unverified"
