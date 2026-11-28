"""Conservative experimental-unit safeguards in ecology and saved workflows."""

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


def _obs(organism: str, unit_id: str, day: int, value: float) -> dict[str, object]:
    return {
        "organism_id": organism,
        "metric_name": "polyp_count",
        "source_record_id": f"{organism}-{day}",
        "observed_at": f"2026-04-0{day}T12:00:00Z",
        "value": value,
        "unit": "count",
        "experimental_unit_id": unit_id,
        "experimental_unit_type": "tank",
    }


def test_fragments_do_not_inflate_independent_tank_count() -> None:
    observations = [
        _obs("frag-1", "tank-A", 1, 10),
        _obs("frag-1", "tank-A", 2, 12),
        _obs("frag-2", "tank-A", 1, 5),
        _obs("frag-2", "tank-A", 2, 9),
        _obs("frag-3", "tank-B", 1, 4),
        _obs("frag-3", "tank-B", 2, 7),
    ]
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert result.evaluated_series_count == 3
    assert result.independent_unit_count == 2
    assert len(result.unit_coverage) == 2
    assert all(row.eligible_for_summary for row in result.unit_coverage)
    assert sum(row.observed_organism_count for row in result.unit_coverage) == 3
    assert result.experimental_unit_type == "tank"
    assert len(result.population_summaries) == 1
    assert result.population_summaries[0].independent_unit_count == 2
    assert result.population_summaries[0].mean_unit_absolute_change == 3.0
    assert [
        (row.experimental_unit_id, row.organism_count, row.mean_absolute_change)
        for row in result.unit_summaries
    ] == [("tank-A", 2, 3.0), ("tank-B", 1, 3.0)]
    assert result.evidence_level == "caller_supplied_unverified"


def test_missing_followup_excludes_whole_tank() -> None:
    observations = [
        _obs("frag-1", "tank-A", 1, 10),
        _obs("frag-1", "tank-A", 2, 12),
        _obs("frag-2", "tank-A", 1, 5),
    ]
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert result.independent_unit_count == 1
    assert result.unit_summaries == []
    assert result.excluded_units[0].reason == "missing_followup"
    assert len(result.unit_coverage) == 1
    coverage = result.unit_coverage[0]
    assert coverage.observed_organism_count == 2
    assert coverage.complete_organism_count == 1
    assert coverage.missing_followup_organism_count == 1
    assert coverage.eligible_for_summary is False
    assert coverage.exclusion_reason == "missing_followup"


def test_reassignment_and_missing_design_are_rejected() -> None:
    observations = [
        _obs("frag-1", "tank-A", 1, 10),
        _obs("frag-1", "tank-B", 2, 12),
    ]
    with pytest.raises(ValidationError, match="changes experimental units"):
        analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    for row in observations:
        row.pop("experimental_unit_type")
    with pytest.raises(ValidationError, match="experimental_unit_type"):
        analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))


def test_saved_workflow_persists_declared_unit_summary(client: TestClient) -> None:
    project = create_project(client, "Independent-unit ecology workflow")
    project_id = str(project["id"])
    graph = {
        "graph_id": "tank-level-ecology",
        "name": "Descriptive tank-level ecology",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "ecology",
                "node_type": "ecology_longitudinal_analysis",
                "parameters": {
                    "observations": [
                        _obs("frag-1", "tank-A", 1, 10),
                        _obs("frag-1", "tank-A", 2, 12),
                    ]
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-ecology",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "ecology",
                "target_port_id": "project",
            }
        ],
    }
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
    artifacts = detail.json()["artifacts"]
    artifact = next(item for item in artifacts if item["data_type"] == "longitudinal_analysis")
    payload = artifact["payload_json"]
    assert payload["experimental_unit_type"] == "tank"
    assert payload["independent_unit_count"] == 1
    assert payload["unit_coverage"][0]["eligible_for_summary"] is True
    assert payload["unit_coverage"][0]["complete_organism_count"] == 1
    assert payload["unit_summaries"][0]["organism_count"] == 1
    assert payload["population_summaries"][0]["independent_unit_count"] == 1
    assert payload["population_summaries"][0]["mean_unit_absolute_change"] == 2.0
    assert payload["evidence_level"] == "caller_supplied_unverified"


def test_sampling_window_exclusion_has_complete_organisms(client: TestClient) -> None:
    observations = [
        _obs("frag-1", "tank-A", 1, 10),
        _obs("frag-1", "tank-A", 2, 12),
        _obs("frag-2", "tank-A", 1, 5),
        _obs("frag-2", "tank-A", 3, 9),
    ]
    request = LongitudinalAnalysisRequest(observations=observations)
    domain = analyze_longitudinal(request)
    assert domain.unit_summaries == []
    assert domain.unit_coverage[0].eligible_for_summary is False
    assert domain.unit_coverage[0].complete_organism_count == 2
    assert domain.unit_coverage[0].missing_followup_organism_count == 0
    assert domain.unit_coverage[0].exclusion_reason == "nonmatching_sampling_window"
    response = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": observations},
    )
    assert response.status_code == 200, response.text
    assert response.json()["unit_coverage"] == [
        item.model_dump(mode="json") for item in domain.unit_coverage
    ]
