"""Require explicit calendar timestamps for longitudinal scientific provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph, _observations


@pytest.mark.parametrize(
    "invalid",
    [1792700000, 1792700000.5, "1792700000", "1792700000.5", None, [], {}],
)
def test_epoch_or_noncalendar_time_rejected_by_schema_and_api(
    client: TestClient, invalid: object
) -> None:
    observations = _observations()
    observations[0]["observed_at"] = invalid
    payload = {"observations": observations}
    with pytest.raises(SchemaValidationError, match="explicit ISO 8601 calendar timestamp"):
        LongitudinalAnalysisRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=payload)
    assert response.status_code == 422, response.text


def test_explicit_timezone_offsets_keep_same_reproducibility_fingerprint(
    client: TestClient,
) -> None:
    baseline = _observations()
    offset = _observations()
    offset[0]["observed_at"] = "2026-04-01T08:00:00-04:00"
    first = client.post("/api/v1/ecology/longitudinal-analysis", json={"observations": baseline})
    second = client.post("/api/v1/ecology/longitudinal-analysis", json={"observations": offset})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["analysis_provenance"] == second.json()["analysis_provenance"]
    assert second.json()["evidence_level"] == "caller_supplied_unverified"


def test_python_timezone_aware_datetime_remains_supported() -> None:
    observations = _observations()
    observations[0]["observed_at"] = datetime(2026, 4, 1, 12, tzinfo=UTC)
    parsed = LongitudinalAnalysisRequest.model_validate({"observations": observations})
    assert parsed.observations[0].observed_at == datetime(2026, 4, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize("invalid", [1792700000, "1792700000"])
def test_saved_workflow_cannot_persist_analysis_from_implicit_epoch(
    client: TestClient, invalid: object
) -> None:
    project = create_project(client, "Longitudinal explicit timestamp QC")
    project_id = str(project["id"])
    observations = _observations()
    observations[0]["observed_at"] = invalid
    graph = cast(dict[str, Any], _graph(observations))
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    if saved.status_code != 201:
        assert saved.status_code in {400, 422}, saved.text
        return
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    if queued.status_code != 202:
        assert queued.status_code in {400, 409, 422}, queued.text
        return
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
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "longitudinal_analysis" for artifact in detail.json()["artifacts"]
    )
