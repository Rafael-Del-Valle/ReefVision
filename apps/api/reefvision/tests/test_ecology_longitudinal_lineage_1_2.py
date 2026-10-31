"""Parent-colony lineage and declared-unit checks for repeated-organism ecology."""

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
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _rows(
    *,
    parent_a: str = "colony-A",
    parent_b: str = "colony-B",
    unit_type: str = "Parent Colonies",
    unit_a: str = "colony-unit-1",
    unit_b: str = "colony-unit-1",
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for organism, parent, unit, first in (
        ("frag-A", parent_a, unit_a, 10),
        ("frag-B", parent_b, unit_b, 20),
    ):
        for day, value in ((1, first), (2, first + 2)):
            observations.append(
                {
                    "organism_id": organism,
                    "parent_colony_id": parent,
                    "metric_name": "polyp_count",
                    "source_record_id": f"{organism}-day-{day}",
                    "observed_at": f"2026-04-0{day}T12:00:00Z",
                    "value": value,
                    "unit": "count",
                    "experimental_unit_id": unit,
                    "experimental_unit_type": unit_type,
                }
            )
    return observations


def test_colony_level_rejects_distinct_parents_in_one_unit() -> None:
    with pytest.raises(ValidationError, match="different parent colonies"):
        analyze_longitudinal(LongitudinalAnalysisRequest(observations=_rows()))


def test_colony_level_rejects_parent_split_into_two_independent_units() -> None:
    observations = _rows(parent_b="colony-A", unit_b="colony-unit-2")
    with pytest.raises(ValidationError, match="multiple independent colony units"):
        analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))


def test_parent_reassignment_and_partial_lineage_fail_closed() -> None:
    observations = _rows(parent_b="colony-A", unit_type="tank")
    observations[1]["parent_colony_id"] = "colony-Z"
    with pytest.raises(ValidationError, match="cannot change parent_colony_id"):
        analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    observations[1]["parent_colony_id"] = None
    with pytest.raises(ValidationError, match="Partial parent_colony_id coverage"):
        analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))


def test_tank_design_retains_two_fragments_of_one_parent_as_one_tank() -> None:
    observations = _rows(parent_b="colony-A", unit_type="tank")
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert result.independent_unit_count == 1
    assert result.unit_summaries[0].organism_count == 2
    assert result.evidence_level == "caller_supplied_unverified"
    assert result.analysis_provenance.algorithm_version.startswith("ecology-longitudinal-")


def test_lineage_changes_input_fingerprint_without_promoting_evidence() -> None:
    observations = _rows(parent_b="colony-A", unit_type="tank")
    before = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    observations[2]["parent_colony_id"] = "colony-B"
    observations[3]["parent_colony_id"] = "colony-B"
    after = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert (
        before.analysis_provenance.canonical_input_sha256
        != after.analysis_provenance.canonical_input_sha256
    )
    assert after.evidence_level == "caller_supplied_unverified"


def test_standalone_api_rejects_colony_pseudoreplication(client: TestClient) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json={"observations": _rows()})
    assert response.status_code == 400, response.text
    assert "different parent colonies" in response.json()["detail"]


def test_saved_workflow_fails_without_success_artifact(client: TestClient) -> None:
    project = create_project(client, "Colony lineage longitudinal review")
    project_id = str(project["id"])
    graph = _graph(_rows())
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
    assert "different parent colonies" in body["run"]["error_message"]
    assert not any(row["data_type"] == "longitudinal_analysis" for row in body["artifacts"])
