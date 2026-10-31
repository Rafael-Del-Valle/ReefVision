"""Reject same-day technical replicate photographs in 1.2 ecology workflows."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph, _observations


def _observation(
    organism: str, when: str, source: str, *, metric: str = "polyp_count"
) -> dict[str, object]:
    return {
        "organism_id": organism,
        "metric_name": metric,
        "source_record_id": source,
        "observed_at": when,
        "value": 10,
        "unit": "count",
    }


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("2026-04-01T09:00:00Z", "2026-04-01T17:00:00Z"),
        ("2026-04-01T23:00:00-04:00", "2026-04-02T04:00:00Z"),
    ],
)
def test_same_utc_day_photographs_require_reviewed_aggregation(first: str, second: str) -> None:
    request = LongitudinalAnalysisRequest(
        observations=[
            _observation("frag-A", first, "first"),
            _observation("frag-A", second, "second"),
            _observation("frag-A", "2026-04-04T12:00:00Z", "followup"),
        ]
    )
    with pytest.raises(ValidationError, match="same UTC sampling date"):
        analyze_longitudinal(request)


def test_distinct_organisms_and_metrics_can_share_sampling_dates() -> None:
    observations = [
        _observation(organism, when, f"{organism}-{metric}-{day}", metric=metric)
        for organism, metric in (
            ("frag-A", "polyp_count"),
            ("frag-B", "polyp_count"),
            ("frag-A", "closed_polyp_count"),
        )
        for day, when in (
            (1, "2026-04-01T09:00:00Z"),
            (2, "2026-04-02T11:00:00Z"),
        )
    ]
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert result.evaluated_series_count == 3
    assert result.analysis_provenance.algorithm_version.startswith("ecology-longitudinal-")
    assert result.evidence_level == "caller_supplied_unverified"


def _repeated_capture() -> list[dict[str, object]]:
    observations = _observations()
    observations.append(
        {
            **observations[0],
            "source_record_id": "day0-repeated-photograph",
            "observed_at": "2026-04-01T19:00:00Z",
        }
    )
    return observations


def test_standalone_api_rejects_same_day_technical_replicates(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": _repeated_capture()},
    )
    assert response.status_code == 400, response.text
    assert "same UTC sampling date" in response.json()["detail"]


def test_saved_workflow_fails_closed_without_longitudinal_artifact(
    client: TestClient,
) -> None:
    project = create_project(client, "Same-day capture rejection")
    project_id = str(project["id"])
    graph = _graph(_repeated_capture())
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
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["status"] == "failed"
    assert "same UTC sampling date" in body["run"]["error_message"]
    assert not any(item["data_type"] == "longitudinal_analysis" for item in body["artifacts"])
